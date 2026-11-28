"""Request admission and response hardening. Pure logic over headers and addresses: no sockets, easy to test.

Order applied to every request (see handler.py): host check -> bearer token -> rate limit.
"""
import hmac
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from .. import config as config_module
from ..ratelimit import Decision, RateLimiter
from .http import BadHost, RateLimited, Unauthorized

log = logging.getLogger("timetravel.http")
LOCAL_ORIGIN = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$")
EXPOSED_HEADERS = "X-Request-Id, Retry-After, X-RateLimit-Limit, X-RateLimit-Remaining"
ALLOWED_REQUEST_HEADERS = "Content-Type, Authorization, Last-Event-ID, X-Request-Id"


def build_limiters(cfg) -> Dict[str, RateLimiter]:
    """One limiter per traffic class. Reads are cheap and frequent (UI polling); writes start recoveries."""
    return {
        "read": RateLimiter(cfg.rate_read_per_minute, cfg.rate_read_burst),
        "write": RateLimiter(cfg.rate_write_per_minute, cfg.rate_write_burst),
        "auth": RateLimiter(cfg.rate_auth_fail_per_minute, max(1, cfg.rate_auth_fail_per_minute)),
    }


class Security:
    def __init__(self, cfg, limiters: Optional[Dict[str, RateLimiter]] = None):
        self.cfg = cfg
        self.limiters = limiters if limiters is not None else build_limiters(cfg)

    # ------------------------------------------------------------------ who is calling
    def client_ip(self, headers, peer: str) -> str:
        """The address rate limits are keyed on. X-Forwarded-For is only believed behind a proxy you control
        (TT_TRUST_PROXY=1); we take its right-most entry, the one our own proxy appended, because the left-hand
        entries are client-supplied and trivially spoofed."""
        if self.cfg.trust_proxy:
            forwarded = [p.strip() for p in (headers.get("X-Forwarded-For") or "").split(",") if p.strip()]
            if forwarded:
                return forwarded[-1]
        return peer

    # ------------------------------------------------------------------ host / origin / CORS
    def host_ok(self, headers) -> bool:
        """Refuse unexpected Host headers (DNS-rebinding defence). Automatic only while bound to loopback."""
        allowed = set(self.cfg.allowed_hosts)
        if not allowed and self.cfg.host in config_module.LOOPBACK_HOSTS:
            allowed = {"localhost", "127.0.0.1", "::1"}
        if not allowed:
            return True
        host = (headers.get("Host") or "").strip().lower()
        if host.startswith("["):                                  # [::1]:8000
            host = host[1:].split("]")[0]
        elif host.count(":") == 1:
            host = host.split(":")[0]
        return host in allowed

    def origin_allowed(self, origin: str) -> bool:
        """CORS allow-list: TT_ALLOWED_ORIGINS when set, otherwise only local dev servers."""
        if self.cfg.allowed_origins:
            return origin.rstrip("/") in self.cfg.allowed_origins
        return bool(LOCAL_ORIGIN.match(origin))

    @staticmethod
    def same_origin(origin: str, headers) -> bool:
        """True when the page that made the request was served by this very server (Origin host == Host)."""
        host = (headers.get("Host") or "").lower()
        return bool(host) and urlsplit(origin).netloc.lower() == host

    def cors_headers(self, headers) -> List[Tuple[str, str]]:
        origin = headers.get("Origin", "")
        if not origin or not self.origin_allowed(origin):
            return []
        return [("Access-Control-Allow-Origin", origin), ("Vary", "Origin"),
                ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                ("Access-Control-Allow-Headers", ALLOWED_REQUEST_HEADERS),
                ("Access-Control-Expose-Headers", EXPOSED_HEADERS)]

    def check_post_origin(self, headers) -> bool:
        """A web page on another site must not drive the API; the app served by this server itself may."""
        origin = headers.get("Origin")
        return not origin or self.origin_allowed(origin) or self.same_origin(origin, headers)

    # ------------------------------------------------------------------ response hardening
    def response_headers(self) -> List[Tuple[str, str]]:
        headers = [("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"),
                   ("Referrer-Policy", "no-referrer"),
                   ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
                   ("Cross-Origin-Opener-Policy", "same-origin")]
        if self.cfg.csp:
            headers.append(("Content-Security-Policy", self.cfg.csp))
        return headers

    # ------------------------------------------------------------------ admission
    def authorized(self, headers) -> bool:
        token = self.cfg.api_token
        if not token:
            return True
        supplied = headers.get("Authorization", "")
        return supplied.startswith("Bearer ") and hmac.compare_digest(supplied[7:], token)

    def check_auth(self, headers, ip: str, path: str) -> None:
        """Raise 401 for /api/* when a token is configured (health stays open). Repeated failures from one address
        are locked out (429) before the token is even compared."""
        if not path.startswith("/api/") or path == "/api/health" or self.authorized(headers):
            return
        limiter = self.limiters["auth"]
        if self.cfg.rate_limit_enabled:
            locked = limiter.blocked(ip)
            if not locked.allowed:
                raise RateLimited(f"Too many failed attempts. Retry in {locked.retry_after}s.",
                                  headers={"Retry-After": locked.retry_after})
            limiter.check(ip)                                    # spend a token: this attempt failed
        raise Unauthorized("missing or invalid bearer token", headers={"WWW-Authenticate": "Bearer"})

    def check_rate(self, method: str, path: str, ip: str, request_id: str = "") -> Dict[str, Any]:
        """Charge the request to the client's read or write bucket. Returns headers to attach to the response."""
        if not self.cfg.rate_limit_enabled or not path.startswith("/api/") or path == "/api/health":
            return {}
        bucket = "write" if method == "POST" else "read"
        decision: Decision = self.limiters[bucket].check(ip)
        headers = {"X-RateLimit-Limit": decision.limit, "X-RateLimit-Remaining": decision.remaining}
        if not decision.allowed:
            log.warning("request_id=%s rate limited ip=%s bucket=%s", request_id, ip, bucket)
            raise RateLimited(f"Too many requests. Retry in {decision.retry_after}s.",
                              headers={**headers, "Retry-After": decision.retry_after})
        return headers

    def admit(self, method: str, path: str, headers, ip: str, request_id: str = "") -> Dict[str, Any]:
        """The whole gate. Raises an HttpError to reject; otherwise returns rate-limit headers for the response."""
        if not self.host_ok(headers):
            raise BadHost("unexpected Host header")
        if method == "OPTIONS":
            return {}
        self.check_auth(headers, ip, path)
        return self.check_rate(method, path, ip, request_id)

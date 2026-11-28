"""Apex Gear + Time-Travel Mission Control. Run: python3 server.py  ->  http://localhost:8000"""
import hmac
import json
import logging
import os
import re
import select
import socket
import sqlite3
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from timetravel import __version__, agent, appcode, audit, config, db, seed, sse, tools
from timetravel.ratelimit import Decision, RateLimiter

cfg = config.load()          # every tunable comes from here (see timetravel/config.py); invalid values fail at startup
log = logging.getLogger("timetravel.http")
STARTED_AT = time.time()

WARM = {"ms": None, "at": None}
SHOW = ["APX-0007", "APX-0042", "APX-0100", "APX-0555", "APX-0777"]      # SKUs the dashboard displays
APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "dist")   # built React app (npm run build)
MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
        ".json": "application/json", ".ico": "image/x-icon", ".map": "application/json"}
# place_order() already contains "WHERE sku = ?", so only the scoped sync_stock statement proves the bug is fixed.
PATCHED_MARK = "UPDATE inventory SET stock = ? WHERE sku = ?"
LOCAL_ORIGIN = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$")

MAX_BODY_BYTES = cfg.max_body_bytes          # reject bigger POST bodies with 413
REQUEST_TIMEOUT = cfg.request_timeout        # slow or stalled clients are dropped
MAX_SSE_STREAMS = cfg.max_sse_streams        # each stream pins a server thread
CHANGELOG_MAX_ROWS = cfg.changelog_max_rows  # 0 keeps everything
PRUNE_EVERY_TICKS = 150                      # warm_loop ticks (4s each) = 10 min
SSE_SLOTS = threading.BoundedSemaphore(MAX_SSE_STREAMS)


def api_token():
    """Optional shared secret. Unset means open (fine for localhost demos); set it before exposing the port."""
    return os.getenv("TT_API_TOKEN", cfg.api_token)


def build_limiters():
    """One limiter per traffic class. Reads are cheap and frequent (UI polling); writes start recoveries."""
    return {
        "read": RateLimiter(cfg.rate_read_per_minute, cfg.rate_read_burst),
        "write": RateLimiter(cfg.rate_write_per_minute, cfg.rate_write_burst),
        "auth": RateLimiter(cfg.rate_auth_fail_per_minute, max(1, cfg.rate_auth_fail_per_minute)),
    }


LIMITERS = build_limiters()
RATE_LIMIT_ENABLED = cfg.rate_limit_enabled


def authorized(headers):
    token = api_token()
    if not token:
        return True
    supplied = headers.get("Authorization", "")
    return supplied.startswith("Bearer ") and hmac.compare_digest(supplied[7:], token)


def health():
    """Liveness plus a cheap DB check. Never requires auth so load balancers and Docker can call it."""
    try:
        with db.LOCK:
            conn = db.connect()
            try:
                conn.execute("SELECT 1").fetchone()
            finally:
                conn.close()
        database = "ok"
    except Exception as error:   # report, do not crash the probe
        database = f"error: {error}"
    return {"status": "ok" if database == "ok" else "degraded", "version": __version__,
            "uptime_seconds": round(time.time() - STARTED_AT, 1), "database": database,
            "llm_provider": os.getenv("TT_LLM_PROVIDER", "gemini"), "auth": "token" if api_token() else "open"}


def warm_tick():
    """One warm-up measurement. Takes no application lock: SQLite's online backup reads a consistent
    snapshot, and in WAL mode it does not block writers, so API requests never queue behind it."""
    c = db.connect()
    m = None
    try:
        t = time.perf_counter()
        m = db.clone(c, ":memory:")
        WARM.update(ms=round((time.perf_counter() - t) * 1000, 1), at=time.time())
    finally:
        if m is not None:
            m.close()
        c.close()


def prune_tick():
    """Trim the legacy changelog. Takes the lock because recovery reads it as one consistent unit."""
    with db.LOCK:
        c = db.connect()
        try:
            return db.prune_changelog(c, CHANGELOG_MAX_ROWS)
        finally:
            c.close()


def warm_loop():
    """Background upkeep: keeps the branch engine hot and bounds the changelog. Never dies silently."""
    ticks, failing = 0, False
    while True:
        try:
            warm_tick()
            if ticks % PRUNE_EVERY_TICKS == 0:
                removed = prune_tick()
                if removed:
                    log.info("pruned %d old changelog rows (keeping newest %d)", removed, CHANGELOG_MAX_ROWS)
            failing = False
        except Exception:
            if not failing:                      # log the first failure of a streak, not every 4 seconds
                log.exception("warm loop failed; will keep retrying")
            failing = True
        ticks += 1
        time.sleep(4)


def api_state():
    with db.LOCK:
        c = db.connect()
        inv = c.execute("SELECT COUNT(*) n, SUM(stock) u, SUM(stock=0) z FROM inventory").fetchone()
        sample = [dict(r) for r in c.execute(
            f"SELECT sku,name,stock FROM inventory WHERE sku IN ({','.join('?' * len(SHOW))}) ORDER BY sku", SHOW)]
        orders = [dict(r) for r in c.execute(
            "SELECT o.id,o.customer_id,o.total_cents,o.status,o.created_at,cu.name AS customer "
            "FROM orders o LEFT JOIN customers cu ON cu.id=o.customer_id ORDER BY o.id DESC LIMIT 6")]
        for o in orders:
            o["items"] = [dict(r) for r in c.execute(
                "SELECT oi.sku, i.name, oi.qty FROM order_items oi LEFT JOIN inventory i ON i.sku=oi.sku "
                "WHERE oi.order_id=? ORDER BY oi.id", (o["id"],))]
        inc = tools.detect_incident(c)
        win = db.clock.now() - 600
        dots = [dict(r) for r in c.execute("SELECT id, created_at ts FROM orders WHERE created_at > ?", (win,))]
        evts = db.last_change_id(c)
        c.close()
    src = appcode.read_source()
    return {"now": db.clock.now(), "inventory": {"skus": inv["n"], "units": inv["u"], "zero": inv["z"], "sample": sample},
            "orders": orders, "incident": inc, "order_dots": dots, "patched": PATCHED_MARK in src,
            "warm": {**WARM, "events": evts}}


class NotFound(KeyError):
    """An unknown route or session (404). A plain KeyError from a handler means a missing request field (400)."""


def post(path, body):
    if path == "/api/orders":
        with db.LOCK:
            c = db.connect()
            try:
                return appcode.fn("place_order")(c, body)
            finally:
                c.close()
    if path == "/api/admin/sync-stock":
        with db.LOCK:
            c = db.connect()
            try:
                return appcode.fn("sync_stock")(c, body)
            finally:
                c.close()
    if path.partition("/api/")[2].startswith("demo/") and not cfg.demo_routes:
        raise NotFound(f"unknown route {path}")                  # TT_DEMO_ROUTES=0 hides the destructive demo helpers
    if path == "/api/demo/reset":
        agent.SESSIONS.clear(); seed.reset(); return {"ok": True}
    if path == "/api/demo/crash":     # the warehouse feed marks ONE sku sold out -> buggy handler wipes all
        return post("/api/admin/sync-stock", {"sku": cfg.demo_crash_sku, "stock": 0})
    if path == "/api/demo/orders":
        return {"orders": seed.demo_orders()}
    if path == "/api/rewind":
        return {"id": agent.start(body.get("prompt", "")).id}
    for action in ("approve", "discard", "undo"):
        if path.startswith("/api/session/") and path.endswith("/" + action):
            sid = path.split("/")[3]
            if sid not in agent.SESSIONS:
                raise NotFound("session not found")
            return getattr(agent, action)(sid).to_json()
    raise NotFound(f"unknown route {path}")


class BadRequest(ValueError):
    """The client sent something we refuse to process (400, or the given status)."""
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class H(BaseHTTPRequestHandler):
    timeout = REQUEST_TIMEOUT        # StreamRequestHandler applies this to the socket: no stalled-client thread leaks

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def log_message(self, *a):
        pass                              # replaced by the structured access log in _send()

    def _begin(self):
        self._t0 = time.perf_counter()
        self._rate_headers = {}
        incoming = self.headers.get("X-Request-Id", "")
        self._rid = incoming if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", incoming) else uuid.uuid4().hex[:12]

    def _client_closed(self):
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            if not readable:
                return False
            return self.connection.recv(1, socket.MSG_PEEK) == b""
        except (OSError, ValueError):
            return True

    def _origin_allowed(self, origin):
        """CORS allow-list: TT_ALLOWED_ORIGINS when set, otherwise only local dev servers."""
        if cfg.allowed_origins:
            return origin.rstrip("/") in cfg.allowed_origins
        return bool(LOCAL_ORIGIN.match(origin))

    def _same_origin(self, origin):
        """True when the page that made the request was served by this very server (Origin host == Host)."""
        host = (self.headers.get("Host") or "").lower()
        return bool(host) and urlsplit(origin).netloc.lower() == host

    def _cors(self):
        """Let allow-listed origins call the API from the browser. Other origins get no CORS headers."""
        origin = self.headers.get("Origin", "")
        if origin and self._origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Last-Event-ID, X-Request-Id")
            self.send_header("Access-Control-Expose-Headers",
                             "X-Request-Id, Retry-After, X-RateLimit-Limit, X-RateLimit-Remaining")

    def end_headers(self):
        """Security headers on every response, including redirects, errors and event streams."""
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        if cfg.csp:
            self.send_header("Content-Security-Policy", cfg.csp)
        super().end_headers()

    def client_ip(self):
        """The address rate limits are keyed on. X-Forwarded-For is only believed behind a proxy you control
        (TT_TRUST_PROXY=1); we take its right-most entry, the one our own proxy appended, because the left-hand
        entries are client-supplied and trivially spoofed."""
        if cfg.trust_proxy:
            forwarded = [p.strip() for p in (self.headers.get("X-Forwarded-For") or "").split(",") if p.strip()]
            if forwarded:
                return forwarded[-1]
        return self.client_address[0]

    def _send(self, code, body, ctype="application/json", extra_headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if urlsplit(self.path).path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")       # live state must never come from a cache
        for name, value in {**getattr(self, "_rate_headers", {}), **(extra_headers or {})}.items():
            self.send_header(name, str(value))
        rid = getattr(self, "_rid", None)
        if rid:
            self.send_header("X-Request-Id", rid)
        self._cors()
        self.end_headers()
        self.wfile.write(data)
        if rid:
            ms = (time.perf_counter() - self._t0) * 1000
            log.info("request_id=%s method=%s path=%s status=%s ms=%.1f", rid, self.command, urlsplit(self.path).path, code, ms)

    def _error(self, status, code, message, headers=None):
        """Every error body has the same shape: {"error": human message, "code": MACHINE_CODE, "request_id": id}."""
        self._send(status, {"error": message, "code": code, "request_id": getattr(self, "_rid", None)},
                   extra_headers=headers)

    def _host_ok(self):
        """Refuse unexpected Host headers (DNS-rebinding defence). Automatic only while bound to loopback."""
        allowed = set(cfg.allowed_hosts)
        if not allowed and cfg.host in config.LOOPBACK_HOSTS:
            allowed = {"localhost", "127.0.0.1", "::1"}
        if not allowed:
            return True
        host = (self.headers.get("Host") or "").strip().lower()
        if host.startswith("["):                                  # [::1]:8000
            host = host[1:].split("]")[0]
        elif host.count(":") == 1:
            host = host.split(":")[0]
        return host in allowed

    def _rate_limit(self, path):
        """Charge the request to the client's read or write bucket. Returns (rejected, headers to attach)."""
        if not RATE_LIMIT_ENABLED or not path.startswith("/api/") or path == "/api/health":
            return False, {}
        bucket = "write" if self.command == "POST" else "read"
        decision = LIMITERS[bucket].check(self.client_ip())
        headers = {"X-RateLimit-Limit": decision.limit, "X-RateLimit-Remaining": decision.remaining}
        if not decision.allowed:
            log.warning("request_id=%s rate limited ip=%s bucket=%s", self._rid, self.client_ip(), bucket)
            self._error(429, "RATE_LIMITED", f"Too many requests. Retry in {decision.retry_after}s.",
                        {**headers, "Retry-After": decision.retry_after})
            return True, headers
        return False, headers

    def _deny_unless_authorized(self):
        """401 for /api/* when TT_API_TOKEN is set (health is always open). Returns True if the request was rejected.
        Repeated failures from one address are locked out (429) before the token is even compared."""
        path = urlsplit(self.path).path
        if not path.startswith("/api/") or path == "/api/health" or authorized(self.headers):
            return False
        limiter = LIMITERS["auth"]
        locked = limiter.blocked(self.client_ip()) if RATE_LIMIT_ENABLED else Decision(True, 0, 0, 0)
        if not locked.allowed:
            self._error(429, "RATE_LIMITED", f"Too many failed attempts. Retry in {locked.retry_after}s.",
                        {"Retry-After": locked.retry_after})
            return True
        if RATE_LIMIT_ENABLED:
            limiter.check(self.client_ip())                      # spend a token: this attempt failed
        self._error(401, "UNAUTHORIZED", "missing or invalid bearer token", {"WWW-Authenticate": "Bearer"})
        return True

    def _gate(self):
        """Checks every request passes before routing: Host header, rate limit, authentication.
        Returns True when the request was already answered (rejected)."""
        path = urlsplit(self.path).path
        if not self._host_ok():
            self._error(421, "BAD_HOST", "unexpected Host header")
            return True
        if self.command != "OPTIONS":
            if self._deny_unless_authorized():
                return True
            rejected, self._rate_headers = self._rate_limit(path)
            return rejected
        return False

    def do_OPTIONS(self):
        self._begin()
        if not self._host_ok():
            return self._error(421, "BAD_HOST", "unexpected Host header")
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _serve_app(self, url_path):
        """Serve the built React app under /app/, falling back to index.html for client-side routes."""
        index = os.path.join(APP_DIR, "index.html")
        if not os.path.exists(index):
            return self._error(404, "NOT_FOUND", "React app is not built. Run: cd frontend && npm install && npm run build:live")
        rel = url_path[len("/app"):].lstrip("/")
        target = os.path.realpath(os.path.join(APP_DIR, rel))
        root = os.path.realpath(APP_DIR)
        if rel and target.startswith(root + os.sep) and os.path.isfile(target):
            with open(target, "rb") as handle:
                return self._send(200, handle.read(), MIME.get(os.path.splitext(target)[1], "application/octet-stream"))
        if os.path.splitext(rel)[1]:     # a missing asset is a real 404, not the app shell
            return self._error(404, "NOT_FOUND", "not found")
        with open(index, "rb") as handle:
            return self._send(200, handle.read(), MIME[".html"])

    def _audit_routes(self, parsed):
        with db.LOCK:
            conn = db.connect()
            try:
                entries = audit.summarize_recoveries(conn)
            finally:
                conn.close()
        if parsed.path == "/api/audit/summary":
            return self._send(200, audit.recovery_stats(entries))
        if parsed.path == "/api/audit":
            q = parse_qs(parsed.query)
            one = lambda k, d="": q.get(k, [d])[0]
            try:
                page = max(1, int(one("page", "1")))
                size = min(100, max(1, int(one("pageSize", "5"))))
            except ValueError:
                return self._error(400, "BAD_REQUEST", "page and pageSize must be integers")
            rows = audit.filter_recoveries(entries, one("search"), one("status"), one("scenario"))
            start = (page - 1) * size
            return self._send(200, {"items": rows[start:start + size], "total": len(rows), "page": page, "pageSize": size})
        sid = parsed.path.split("/")[3]
        for e in entries:
            if e["id"] == sid:
                return self._send(200, e)
        return self._error(404, "NOT_FOUND", "recovery not found")

    def do_GET(self):
        self._begin()
        try:
            if self._gate():
                return
            if self.path == "/api/health":
                return self._send(200, health())
            if self.path == "/favicon.ico":                 # browsers ask for this regardless of the <link> tag
                self.send_response(302)
                self.send_header("Location", "/app/favicon.svg")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.path in ("/", "/index.html"):          # the React app is the only UI
                self.send_response(302)
                self.send_header("Location", "/app/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.path == "/api/state":
                return self._send(200, api_state())

            parsed = urlsplit(self.path)
            if parsed.path == "/app":
                self.send_response(301)
                self.send_header("Location", "/app/")
                self.end_headers()
                return
            if parsed.path.startswith("/app/"):
                return self._serve_app(parsed.path)

            if parsed.path in ("/api/audit", "/api/audit/summary") or (
                    parsed.path.startswith("/api/audit/") and parsed.path.count("/") == 3):
                return self._audit_routes(parsed)

            if parsed.path.startswith("/api/session/") and parsed.path.endswith("/events"):
                parts = parsed.path.strip("/").split("/")
                sid = parts[2] if len(parts) > 2 else ""
                if not sse.validate_session_id(sid):
                    return self._error(400, "BAD_REQUEST", "invalid session id")
                try:
                    header_id = self.headers.get("Last-Event-ID")
                    query_id = parse_qs(parsed.query).get("last_event_id", [None])[0]
                    after_id = sse.parse_last_event_id(header_id if header_id is not None else query_id)
                except ValueError as error:
                    return self._error(400, "BAD_REQUEST", str(error))
                try:
                    historical = sse.read_events_after(sid, after_id)
                except Exception:
                    log.exception("request_id=%s could not read audit history for %s", self._rid, sid)
                    return self._error(500, "INTERNAL", "audit stream unavailable")
                if not historical and sid not in agent.SESSIONS:
                    return self._error(404, "NOT_FOUND", "session or audit history not found")
                if not SSE_SLOTS.acquire(blocking=False):
                    return self._error(503, "BUSY", "too many open event streams, retry shortly", {"Retry-After": 5})

                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("X-Accel-Buffering", "no")
                self._cors()
                self.end_headers()
                try:
                    self.wfile.write(b"retry: 3000\n\n")
                    self.wfile.flush()
                    for frame in sse.iter_sse_frames(sid, after_id, closed=self._client_closed):
                        self.wfile.write(frame.encode("utf-8"))
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    SSE_SLOTS.release()
                return

            if parsed.path.startswith("/api/session/") and parsed.path.endswith("/audit"):
                sid = parsed.path.split("/")[3]
                events = agent.audit_events(sid)
                if not events:
                    return self._error(404, "NOT_FOUND", "audit history not found")
                return self._send(200, {"session_id": sid, "events": events})

            if parsed.path.startswith("/api/session/"):
                sid = parsed.path.split("/")[3]
                if sid not in agent.SESSIONS:
                    return self._error(404, "NOT_FOUND", "session not found")
                return self._send(200, agent.SESSIONS[sid].to_json())

            self._error(404, "NOT_FOUND", "not found")
        except Exception:
            log.exception("request_id=%s unhandled error on GET %s", self._rid, self.path)
            self._error(500, "INTERNAL", "internal error")

    def _read_json_body(self):
        """Read and validate the POST body: bounded size, valid JSON, and a JSON object."""
        raw_length = self.headers.get("Content-Length") or "0"
        if not raw_length.isdigit():
            raise BadRequest("invalid Content-Length")
        n = int(raw_length)
        if n > MAX_BODY_BYTES:
            raise BadRequest(f"request body too large (limit {MAX_BODY_BYTES} bytes)", 413)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, UnicodeDecodeError):
            raise BadRequest("request body is not valid JSON")
        if not isinstance(body, dict):
            raise BadRequest("request body must be a JSON object")
        return body

    def do_POST(self):
        self._begin()
        try:
            if self._gate():
                return
            origin = self.headers.get("Origin")
            # a web page on another site must not drive this API; the app served by this server itself may
            if origin and not (self._origin_allowed(origin) or self._same_origin(origin)):
                return self._error(403, "FORBIDDEN_ORIGIN", "cross-origin requests are not allowed")
            body = self._read_json_body()
            self._send(200, post(self.path, body))
        except BadRequest as e:
            self._error(e.status, "PAYLOAD_TOO_LARGE" if e.status == 413 else "BAD_REQUEST", str(e))
        except NotFound as e:
            self._error(404, "NOT_FOUND", e.args[0])
        except KeyError as e:
            self._error(400, "BAD_REQUEST", f"missing field {e}")
        except sqlite3.OperationalError:        # locked / busy / disk problems are the server's, not the client's
            log.exception("request_id=%s database unavailable on POST %s", self._rid, self.path)
            self._error(503, "DB_BUSY", "database is busy, retry shortly", {"Retry-After": 2})
        except Exception as e:                        # handler-level validation errors carry a message the UI shows
            log.warning("request_id=%s POST %s rejected: %s", self._rid, self.path, e)
            self._error(400, "BAD_REQUEST", str(e))


def main():
    logging.basicConfig(level=cfg.log_level,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if not os.path.exists(db.LIVE):
        seed.reset()
    appcode.reload()
    with db.LOCK:
        c = db.connect()
        try:
            db.ensure_indexes(c)        # databases created before the index existed get it on first start
        finally:
            c.close()
    threading.Thread(target=warm_loop, daemon=True).start()
    host, port = cfg.host, cfg.port        # keep loopback unless you set a token and put it behind TLS
    if host not in config.LOOPBACK_HOSTS and not api_token():
        log.warning("listening on %s with no TT_API_TOKEN set: anyone who can reach the port can reset or rewrite the DB", host)
    if host not in config.LOOPBACK_HOSTS and cfg.demo_routes:
        log.warning("demo routes (/api/demo/*, including reset) are enabled on a public address; set TT_DEMO_ROUTES=0 to hide them")
    if cfg.trust_proxy:
        log.info("TT_TRUST_PROXY on: rate limits use the right-most X-Forwarded-For entry")
    print(f"Mission Control on http://{host}:{port}")
    ThreadingHTTPServer((host, port), H).serve_forever()


if __name__ == "__main__":
    main()

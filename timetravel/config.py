"""Runtime configuration: every tunable lives here, read from environment variables, validated once.

Invalid values fail fast at startup with the variable name in the message, instead of surfacing later as an
obscure error inside a request. Modules keep their own module-level copies (``server.MAX_BODY_BYTES`` ...)
so tests can patch them; this module is the single place that knows names, defaults and valid ranges.
"""
import os
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

# Default Content-Security-Policy for the built React app. Fonts come from Google Fonts (see frontend/index.html).
DEFAULT_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data:; connect-src 'self'; "
    "base-uri 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'"
)


class ConfigError(ValueError):
    """An environment variable holds a value we cannot use."""


def _number(env, name, default, cast, minimum):
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = cast(raw.strip())
    except ValueError:
        raise ConfigError(f"{name}={raw!r} is not a valid {cast.__name__}") from None
    if value < minimum:
        raise ConfigError(f"{name}={raw!r} must be >= {minimum}")
    return value


def _flag(env, name, default):
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name}={raw!r} must be one of 1/0, true/false, yes/no, on/off")


def _csv(env, name) -> Tuple[str, ...]:
    return tuple(part.strip() for part in env.get(name, "").split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    # network
    host: str = "127.0.0.1"
    port: int = 8000
    trust_proxy: bool = False                  # believe X-Forwarded-For (only behind a proxy you control)
    allowed_origins: Tuple[str, ...] = ()      # exact origins for CORS; empty = localhost dev servers only
    allowed_hosts: Tuple[str, ...] = ()        # accepted Host header names; empty = auto (loopback only if bound there)
    # limits
    max_body_bytes: int = 1024 * 1024
    request_timeout: float = 30.0
    max_sse_streams: int = 32
    max_sessions: int = 200
    changelog_max_rows: int = 500_000
    # rate limiting (requests per minute and the burst a client may spend at once; 0 per-minute disables a bucket)
    rate_limit_enabled: bool = True
    rate_read_per_minute: int = 600
    rate_read_burst: int = 120
    rate_write_per_minute: int = 60
    rate_write_burst: int = 20
    rate_auth_fail_per_minute: int = 10
    # security
    api_token: str = ""
    csp: str = DEFAULT_CSP
    demo_routes: bool = True                   # /api/demo/* (reset, crash, orders); turn off for anything public
    # demo + storage
    demo_crash_sku: str = "APX-0007"
    data_dir: str = os.path.join(BASE_DIR, "data")
    pace: float = 0.4
    log_level: str = "INFO"


def load(env: Optional[Mapping[str, str]] = None) -> Settings:
    env = os.environ if env is None else env
    s = Settings(
        host=env.get("HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=_number(env, "PORT", 8000, int, 0),
        trust_proxy=_flag(env, "TT_TRUST_PROXY", False),
        allowed_origins=tuple(o.rstrip("/") for o in _csv(env, "TT_ALLOWED_ORIGINS")),
        allowed_hosts=tuple(h.lower() for h in _csv(env, "TT_ALLOWED_HOSTS")),
        max_body_bytes=_number(env, "TT_MAX_BODY_BYTES", 1024 * 1024, int, 1),
        request_timeout=_number(env, "TT_REQUEST_TIMEOUT", 30.0, float, 0.1),
        max_sse_streams=_number(env, "TT_MAX_SSE_STREAMS", 32, int, 1),
        max_sessions=_number(env, "TT_MAX_SESSIONS", 200, int, 1),
        changelog_max_rows=_number(env, "TT_CHANGELOG_MAX_ROWS", 500_000, int, 0),
        rate_limit_enabled=_flag(env, "TT_RATE_LIMIT", True),
        rate_read_per_minute=_number(env, "TT_RATE_READ_PER_MIN", 600, int, 0),
        rate_read_burst=_number(env, "TT_RATE_READ_BURST", 120, int, 1),
        rate_write_per_minute=_number(env, "TT_RATE_WRITE_PER_MIN", 60, int, 0),
        rate_write_burst=_number(env, "TT_RATE_WRITE_BURST", 20, int, 1),
        rate_auth_fail_per_minute=_number(env, "TT_RATE_AUTH_FAIL_PER_MIN", 10, int, 0),
        api_token=env.get("TT_API_TOKEN", ""),
        csp=env["TT_CSP"] if "TT_CSP" in env else DEFAULT_CSP,
        demo_routes=_flag(env, "TT_DEMO_ROUTES", True),
        demo_crash_sku=env.get("TT_DEMO_SKU", "APX-0007").strip() or "APX-0007",
        data_dir=os.path.abspath(env.get("TT_DATA_DIR") or os.path.join(BASE_DIR, "data")),
        pace=_number(env, "TT_PACE", 0.4, float, 0.0),
        log_level=(env.get("TT_LOG_LEVEL", "INFO").strip() or "INFO").upper(),
    )
    if s.port > 65535:
        raise ConfigError(f"PORT={s.port} is out of range")
    return s

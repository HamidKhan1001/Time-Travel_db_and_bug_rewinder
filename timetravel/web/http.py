"""Types shared by the handler, the router and every route: Request, Response, Stream and the HTTP errors."""
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional


class HttpError(Exception):
    """An error the client should see: becomes ``{"error", "code", "request_id"}`` with this status."""
    status = 500
    code = "INTERNAL"

    def __init__(self, message: str, status: Optional[int] = None, code: Optional[str] = None,
                 headers: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        if status is not None:
            self.status = status
        if code is not None:
            self.code = code
        self.headers = headers or {}


class NotFound(HttpError):
    """An unknown route or session (404). A plain KeyError raised by a handler means a missing field (400)."""
    status, code = 404, "NOT_FOUND"


class BadRequest(HttpError):
    status, code = 400, "BAD_REQUEST"


class PayloadTooLarge(HttpError):
    status, code = 413, "PAYLOAD_TOO_LARGE"


class Unauthorized(HttpError):
    status, code = 401, "UNAUTHORIZED"


class Forbidden(HttpError):
    status, code = 403, "FORBIDDEN_ORIGIN"


class BadHost(HttpError):
    status, code = 421, "BAD_HOST"


class RateLimited(HttpError):
    status, code = 429, "RATE_LIMITED"


class Unavailable(HttpError):
    """The server cannot take this right now (busy database, too many streams); the client may retry."""
    status, code = 503, "BUSY"


@dataclass
class Request:
    """Everything a route needs, with no socket in sight."""
    ctx: Any                                   # AppContext
    method: str
    path: str
    query: Dict[str, List[str]]
    headers: Any                               # case-insensitive mapping (http.client.HTTPMessage)
    client_ip: str
    request_id: str
    params: Dict[str, str] = field(default_factory=dict)
    read_body: Callable[[int], bytes] = lambda n: b""
    client_closed: Callable[[], bool] = lambda: False
    _json: Optional[dict] = None

    def arg(self, name: str, default: Any = "") -> Any:
        return self.query.get(name, [default])[0]

    def json(self) -> dict:
        """The request body: bounded in size, valid JSON, and a JSON object. Read at most once."""
        if self._json is not None:
            return self._json
        raw_length = self.headers.get("Content-Length") or "0"
        if not raw_length.isdigit():
            raise BadRequest("invalid Content-Length")
        n = int(raw_length)
        limit = self.ctx.cfg.max_body_bytes
        if n > limit:
            raise PayloadTooLarge(f"request body too large (limit {limit} bytes)")
        try:
            body = json.loads(self.read_body(n) or b"{}")
        except (ValueError, UnicodeDecodeError):
            raise BadRequest("request body is not valid JSON") from None
        if not isinstance(body, dict):
            raise BadRequest("request body must be a JSON object")
        self._json = body
        return body


@dataclass
class Response:
    status: int = 200
    body: Any = None                            # dict/list -> JSON; bytes -> as is
    content_type: str = "application/json"
    headers: Dict[str, Any] = field(default_factory=dict)


def redirect(location: str, status: int = 302) -> Response:
    return Response(status=status, body=b"", headers={"Location": location})


@dataclass
class Stream:
    """A long-lived response (Server-Sent Events). ``release`` always runs, even if the client vanishes."""
    frames: Iterable[str]
    release: Callable[[], None] = lambda: None
    content_type: str = "text/event-stream; charset=utf-8"
    headers: Dict[str, Any] = field(default_factory=lambda: {
        "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})
    status: int = 200

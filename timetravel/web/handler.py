"""The socket-facing request handler. Every request takes the same path:

    parse -> admit (host, auth, rate limit) -> route -> (POST: parse body) -> run route -> write response

Errors raised anywhere in that path become one JSON shape, ``{"error", "code", "request_id"}``.
"""
import contextlib
import json
import logging
import re
import select
import socket
import sqlite3
import time
import uuid
from http.server import BaseHTTPRequestHandler
from typing import Type
from urllib.parse import parse_qs, urlsplit

from .context import AppContext
from .http import BadRequest, Forbidden, HttpError, NotFound, Request, Response, Stream
from .router import Router

log = logging.getLogger("timetravel.http")
REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


class Handler(BaseHTTPRequestHandler):
    ctx: AppContext                       # bound by make_handler()
    router: Router
    timeout = 30.0                        # replaced per server from cfg.request_timeout: stalled clients cannot pin a thread

    # ------------------------------------------------------------ plumbing
    def handle(self):
        with contextlib.suppress(BrokenPipeError, ConnectionResetError, OSError):   # the client went away: not our error
            super().handle()

    def log_message(self, *args):
        pass                              # replaced by the structured access log in _finish()

    def end_headers(self):
        """Security headers on every response, including redirects, errors and event streams."""
        for name, value in self.ctx.security.response_headers():
            self.send_header(name, value)
        super().end_headers()

    def _client_closed(self):
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            if not readable:
                return False
            return self.connection.recv(1, socket.MSG_PEEK) == b""
        except (OSError, ValueError):
            return True

    # ------------------------------------------------------------ writing responses
    def _begin(self):
        self._t0 = time.perf_counter()
        self._extra = {}                                  # rate-limit headers, once the request was admitted
        incoming = self.headers.get("X-Request-Id", "")
        self._rid = incoming if REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex[:12]
        self._path = urlsplit(self.path).path

    def _finish(self, status):
        ms = (time.perf_counter() - self._t0) * 1000
        log.info("request_id=%s method=%s path=%s status=%s ms=%.1f", self._rid, self.command, self._path, status, ms)

    def _headers(self, status, content_type, length, headers):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("X-Request-Id", self._rid)
        if self._path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")        # live state must never come from a cache
        for name, value in {**self._extra, **headers}.items():
            self.send_header(name, str(value))
        for name, value in self.ctx.security.cors_headers(self.headers):
            self.send_header(name, value)
        self.end_headers()

    def _write(self, result):
        """Turn whatever a route returned into bytes on the wire."""
        if isinstance(result, Stream):
            return self._write_stream(result)
        if not isinstance(result, Response):
            result = Response(200, result)
        body = result.body
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self._finish(result.status)                       # log first: once headers are out the client may already be gone
        self._headers(result.status, result.content_type, len(data), result.headers)
        self.wfile.write(data)

    def _write_stream(self, stream):
        try:
            self._headers(stream.status, stream.content_type, None, stream.headers)
            for frame in stream.frames:
                self.wfile.write(frame.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass                                              # the client went away
        except Exception:
            # Headers are already out, so a second (error) response would corrupt the stream: log and close it.
            log.exception("request_id=%s event stream failed on %s", self._rid, self._path)
            self.close_connection = True
        finally:
            stream.release()
            self._finish(stream.status)

    def _error(self, error):
        body = {"error": error.message, "code": error.code, "request_id": self._rid}
        data = json.dumps(body).encode()
        self._finish(error.status)
        self._headers(error.status, "application/json", len(data), error.headers)
        self.wfile.write(data)

    # ------------------------------------------------------------ the pipeline
    def _request(self):
        return Request(
            ctx=self.ctx, method=self.command, path=self._path, query=parse_qs(urlsplit(self.path).query),
            headers=self.headers, client_ip=self.ctx.security.client_ip(self.headers, self.client_address[0]),
            request_id=self._rid, read_body=self.rfile.read, client_closed=self._client_closed)

    def _serve(self, method):
        self._begin()
        try:
            req = self._request()
            self._extra = self.ctx.security.admit(method, self._path, self.headers, req.client_ip, self._rid)
            if method == "POST":
                if not self.ctx.security.check_post_origin(self.headers):
                    raise Forbidden("cross-origin requests are not allowed")
                req.json()                                   # bad bodies are rejected before any route runs
            match = self.router.match(method, self._path)
            if match is None:
                raise NotFound(f"unknown route {self._path}" if method == "POST" else "not found")
            route, req.params = match
            self._write(route.handler(req))
        except HttpError as error:
            self._error(error)
        except KeyError as error:                            # a route read a field the client did not send
            self._error(BadRequest(f"missing field {error}"))
        except sqlite3.OperationalError:                     # locked / busy / disk: the server's problem, not the client's
            log.exception("request_id=%s database unavailable on %s %s", self._rid, method, self._path)
            self._error(HttpError("database is busy, retry shortly", 503, "DB_BUSY", {"Retry-After": 2}))
        except Exception as error:
            if method == "POST":                             # route-level validation errors carry a message the UI shows
                log.warning("request_id=%s POST %s rejected: %s", self._rid, self._path, error)
                self._error(BadRequest(str(error)))
            else:
                log.exception("request_id=%s unhandled error on %s %s", self._rid, method, self._path)
                self._error(HttpError("internal error"))

    def do_GET(self):
        self._serve("GET")

    def do_POST(self):
        self._serve("POST")

    def do_OPTIONS(self):
        self._begin()
        try:
            self.ctx.security.admit("OPTIONS", self._path, self.headers, self.client_address[0], self._rid)
        except HttpError as error:
            return self._error(error)
        self._finish(204)
        self._headers(204, "text/plain", 0, {})


def make_handler(ctx: AppContext, router: Router) -> Type[Handler]:
    """A handler class bound to one AppContext and Router, so several servers with different settings can coexist."""
    return type("BoundHandler", (Handler,), {"ctx": ctx, "router": router, "timeout": ctx.cfg.request_timeout})

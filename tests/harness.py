"""Shared helpers for tests that exercise the HTTP layer.

``start_server`` builds a fresh AppContext (defaults from timetravel.config, never the developer's environment)
and serves it on a free port, so a test changes behaviour by passing settings instead of patching module globals.
``call_route`` runs a route function directly (no sockets) for fast contract tests.
"""
import dataclasses
import json
import threading
from dataclasses import dataclass
from typing import Any, Optional

from timetravel import config
from timetravel.web.app import make_server
from timetravel.web.context import AppContext
from timetravel.web.http import NotFound, Request, Response
from timetravel.web.routes import build_router
from timetravel.web.routes.state import build_state


def default_settings(**overrides) -> config.Settings:
    """Library defaults with explicit overrides: independent of whatever TT_* variables the shell has."""
    return dataclasses.replace(config.load({}), **overrides)


def make_context(**overrides) -> AppContext:
    return AppContext.create(default_settings(**overrides))


@dataclass
class RunningServer:
    httpd: Any
    thread: threading.Thread
    ctx: AppContext

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


def start_server(ctx: Optional[AppContext] = None, **overrides) -> RunningServer:
    ctx = ctx or make_context(**overrides)
    httpd = make_server(ctx, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return RunningServer(httpd, thread, ctx)


def call_route(method: str, path: str, body: Optional[dict] = None, ctx: Optional[AppContext] = None):
    """Run the matching route function and return its payload. Raises what the route raises (NotFound for no route)."""
    ctx = ctx or make_context()
    match = build_router().match(method, path)
    if match is None:
        raise NotFound(f"unknown route {path}")
    raw = json.dumps(body or {}).encode()
    request = Request(ctx=ctx, method=method, path=path, query={}, headers={"Content-Length": str(len(raw))},
                      client_ip="127.0.0.1", request_id="test", read_body=lambda n: raw)
    route, request.params = match
    result = route.handler(request)
    return result.body if isinstance(result, Response) else result


def api_state(ctx: Optional[AppContext] = None) -> dict:
    return build_state(ctx or make_context())

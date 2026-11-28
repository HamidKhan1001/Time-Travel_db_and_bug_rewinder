"""A route table: (method, pattern) -> function(Request) -> Response | dict | Stream.

Patterns use ``{name}`` for one path segment and ``{name:path}`` for the rest of the path. Routes are matched in
registration order, so register static paths (``/api/audit/summary``) before parameterised ones (``/api/audit/{id}``).
``Router.routes`` is also what the OpenAPI contract test reads, so the spec and the code cannot drift apart.
"""
import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

_PARAM = re.compile(r"\{(\w+)(?::(path))?\}")


@dataclass(frozen=True)
class Route:
    method: str
    pattern: str                    # as written, e.g. "/api/session/{id}/approve"
    handler: Callable
    regex: "re.Pattern[str]"

    @property
    def openapi_path(self) -> str:
        return _PARAM.sub(lambda m: "{" + m.group(1) + "}", self.pattern)


def _compile(pattern: str) -> "re.Pattern[str]":
    def part(m):
        return f"(?P<{m.group(1)}>.+)" if m.group(2) else f"(?P<{m.group(1)}>[^/]+)"
    out, last = "", 0
    for m in _PARAM.finditer(pattern):
        out += re.escape(pattern[last:m.start()]) + part(m)
        last = m.end()
    return re.compile("^" + out + re.escape(pattern[last:]) + "$")


class Router:
    def __init__(self) -> None:
        self.routes: List[Route] = []

    def add(self, method: str, pattern: str, handler: Callable) -> None:
        self.routes.append(Route(method.upper(), pattern, handler, _compile(pattern)))

    def get(self, pattern: str, handler: Callable) -> None:
        self.add("GET", pattern, handler)

    def post(self, pattern: str, handler: Callable) -> None:
        self.add("POST", pattern, handler)

    def match(self, method: str, path: str) -> Optional[Tuple[Route, Dict[str, str]]]:
        for route in self.routes:
            if route.method != method:
                continue
            m = route.regex.match(path)
            if m:
                return route, m.groupdict()
        return None

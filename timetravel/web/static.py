"""Serve the built React app (frontend/dist) under /app/, falling back to index.html for client-side routes."""
import os
from typing import Optional

from .http import Response

APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend", "dist")
MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
        ".json": "application/json", ".ico": "image/x-icon", ".map": "application/json"}
NOT_BUILT = "React app is not built. Run: cd frontend && npm install && npm run build:live"


def _read(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def serve_app(rel: str, app_dir: Optional[str] = None) -> Response:
    """``rel`` is the part of the URL after /app/. Never serves anything outside ``app_dir``."""
    app_dir = app_dir or APP_DIR
    index = os.path.join(app_dir, "index.html")
    if not os.path.exists(index):
        return Response(404, {"error": NOT_BUILT, "code": "NOT_FOUND"})
    rel = rel.lstrip("/")
    root = os.path.realpath(app_dir)
    target = os.path.realpath(os.path.join(root, rel))
    if rel and target.startswith(root + os.sep) and os.path.isfile(target):
        return Response(200, _read(target), MIME.get(os.path.splitext(target)[1], "application/octet-stream"))
    if os.path.splitext(rel)[1]:                      # a missing asset is a real 404, not the app shell
        return Response(404, {"error": "not found", "code": "NOT_FOUND"})
    return Response(200, _read(index), MIME[".html"])

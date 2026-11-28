"""The React app: redirects into /app/ and the static files themselves."""
from ..http import Request, redirect
from ..static import serve_app

APP_PREFIX = "/app"


def to_app(req: Request):
    return redirect(APP_PREFIX + "/")


def favicon(req: Request):                              # browsers ask for /favicon.ico regardless of the <link> tag
    return redirect(APP_PREFIX + "/favicon.svg")


def app_root_redirect(req: Request):
    return redirect(APP_PREFIX + "/", 301)


def app_index(req: Request):
    return serve_app("")


def app_file(req: Request):
    return serve_app(req.params["path"])


def register(router):
    router.get("/", to_app)
    router.get("/index.html", to_app)
    router.get("/favicon.ico", favicon)
    router.get(APP_PREFIX, app_root_redirect)
    router.get(APP_PREFIX + "/", app_index)
    router.get(APP_PREFIX + "/{path:path}", app_file)

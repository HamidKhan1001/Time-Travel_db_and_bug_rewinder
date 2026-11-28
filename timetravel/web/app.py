"""Wiring and process entry point: ``python3 server.py`` ends up in :func:`main`."""
import logging
import os
from http.server import ThreadingHTTPServer
from typing import Optional

from .. import appcode, config, db, seed
from .context import AppContext
from .handler import make_handler
from .maintenance import Maintenance
from .routes import build_router

log = logging.getLogger("timetravel.http")


def make_server(ctx: AppContext, host: Optional[str] = None, port: Optional[int] = None) -> ThreadingHTTPServer:
    """A server bound to ``ctx``. Pass port 0 to let the OS choose (tests)."""
    handler = make_handler(ctx, build_router())
    return ThreadingHTTPServer((ctx.cfg.host if host is None else host, ctx.cfg.port if port is None else port), handler)


def bootstrap(ctx: AppContext) -> None:
    """Make sure there is a database to serve, load the handler code and index old databases."""
    if not os.path.exists(db.LIVE):
        seed.reset()
    appcode.reload()
    with db.LOCK:
        conn = db.connect()
        try:
            db.ensure_indexes(conn)        # databases created before an index existed get it on first start
        finally:
            conn.close()


def warn_about_exposure(cfg: config.Settings) -> None:
    public = cfg.host not in config.LOOPBACK_HOSTS
    if public and not cfg.api_token:
        log.warning("listening on %s with no TT_API_TOKEN set: anyone who can reach the port can reset or rewrite the DB", cfg.host)
    if public and cfg.demo_routes:
        log.warning("demo routes (/api/demo/*, including reset) are enabled on a public address; set TT_DEMO_ROUTES=0 to hide them")
    if cfg.trust_proxy:
        log.info("TT_TRUST_PROXY on: rate limits use the right-most X-Forwarded-For entry")


def main() -> None:
    cfg = config.load()
    logging.basicConfig(level=cfg.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ctx = AppContext.create(cfg)
    bootstrap(ctx)
    Maintenance(ctx).start()
    warn_about_exposure(cfg)
    server = make_server(ctx)
    print(f"Mission Control on http://{cfg.host}:{cfg.port}")
    server.serve_forever()

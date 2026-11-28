"""GET /api/health: liveness plus a cheap DB check. Never requires auth so load balancers and Docker can call it."""
import os
import time

from ... import __version__, db
from ..http import Request


def health(req: Request) -> dict:
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
            "uptime_seconds": round(time.time() - req.ctx.started_at, 1), "database": database,
            "llm_provider": os.getenv("TT_LLM_PROVIDER", "gemini"),
            "auth": "token" if req.ctx.cfg.api_token else "open"}


def register(router):
    router.get("/api/health", health)

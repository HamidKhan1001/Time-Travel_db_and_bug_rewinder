"""POST /api/demo/*: helpers that stage the demo (reset, crash, seed orders). Hidden by TT_DEMO_ROUTES=0."""
from ... import agent, seed
from ..http import NotFound, Request
from . import orders


def _guarded(fn):
    def route(req: Request):
        if not req.ctx.cfg.demo_routes:
            raise NotFound(f"unknown route {req.path}")
        return fn(req)
    return route


def reset(req: Request):
    agent.SESSIONS.clear()
    seed.reset()
    return {"ok": True}


def crash(req: Request):
    """The warehouse feed marks ONE sku sold out -> the buggy handler wipes them all."""
    req._json = {"sku": req.ctx.cfg.demo_crash_sku, "stock": 0}
    return orders.sync_stock(req)


def demo_orders(req: Request):
    return {"orders": seed.demo_orders()}


def register(router):
    router.post("/api/demo/reset", _guarded(reset))
    router.post("/api/demo/crash", _guarded(crash))
    router.post("/api/demo/orders", _guarded(demo_orders))

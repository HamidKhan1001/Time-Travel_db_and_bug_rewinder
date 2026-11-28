"""POST /api/orders and /api/admin/sync-stock: the two application endpoints whose handlers live in app/handlers.py.

The handler code is loaded (and, after a recovery, replaced) at runtime by ``appcode``, which is what makes the
demo bug fixable without a restart.
"""
from ... import appcode, db
from ..http import Request


def _call_handler(name: str, body: dict):
    with db.LOCK:
        conn = db.connect()
        try:
            return appcode.fn(name)(conn, body)
        finally:
            conn.close()


def place_order(req: Request):
    return _call_handler("place_order", req.json())


def sync_stock(req: Request):
    return _call_handler("sync_stock", req.json())


def register(router):
    router.post("/api/orders", place_order)
    router.post("/api/admin/sync-stock", sync_stock)

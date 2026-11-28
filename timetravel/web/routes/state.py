"""GET /api/state: the dashboard read model (inventory, recent orders, incident, warm-up numbers)."""
from ... import appcode, db, tools
from ..http import Request

# place_order() already contains "WHERE sku = ?", so only the scoped sync_stock statement proves the bug is fixed.
PATCHED_MARK = "UPDATE inventory SET stock = ? WHERE sku = ?"
RECENT_ORDERS = 6
ORDER_DOT_WINDOW_SECONDS = 600


def build_state(ctx) -> dict:
    skus = list(ctx.cfg.dashboard_skus)
    with db.LOCK:
        conn = db.connect()
        try:
            inv = conn.execute("SELECT COUNT(*) n, SUM(stock) u, SUM(stock=0) z FROM inventory").fetchone()
            sample = [dict(r) for r in conn.execute(
                f"SELECT sku,name,stock FROM inventory WHERE sku IN ({','.join('?' * len(skus))}) ORDER BY sku", skus)]
            orders = [dict(r) for r in conn.execute(
                "SELECT o.id,o.customer_id,o.total_cents,o.status,o.created_at,cu.name AS customer "
                "FROM orders o LEFT JOIN customers cu ON cu.id=o.customer_id ORDER BY o.id DESC LIMIT ?",
                (RECENT_ORDERS,))]
            for o in orders:
                o["items"] = [dict(r) for r in conn.execute(
                    "SELECT oi.sku, i.name, oi.qty FROM order_items oi LEFT JOIN inventory i ON i.sku=oi.sku "
                    "WHERE oi.order_id=? ORDER BY oi.id", (o["id"],))]
            incident = tools.detect_incident(conn)
            window = db.clock.now() - ORDER_DOT_WINDOW_SECONDS
            dots = [dict(r) for r in conn.execute("SELECT id, created_at ts FROM orders WHERE created_at > ?", (window,))]
            events = db.last_change_id(conn)
        finally:
            conn.close()
    return {"now": db.clock.now(),
            "inventory": {"skus": inv["n"], "units": inv["u"], "zero": inv["z"], "sample": sample},
            "orders": orders, "incident": incident, "order_dots": dots,
            "patched": PATCHED_MARK in appcode.read_source(),
            "warm": {**ctx.warm, "events": events}}


def state(req: Request) -> dict:
    return build_state(req.ctx)


def register(router):
    router.get("/api/state", state)

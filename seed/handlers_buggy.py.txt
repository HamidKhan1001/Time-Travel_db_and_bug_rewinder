"""Apex Gear storefront request handlers (the application code the agent can patch)."""
import uuid


def run_sql(conn, source, sql, params=()):
    cur = conn.execute(sql, params)
    conn.execute("INSERT INTO query_log(ts, source, sql, rows_affected) VALUES (app_now(), ?, ?, ?)",
                 (source, sql, cur.rowcount))
    return cur.rowcount


def sync_stock(conn, payload):
    """POST /api/admin/sync-stock - warehouse feed sets the on-hand count for ONE sku."""
    sku = payload.get("sku")
    stock = int(payload.get("stock", 0))
    sql = "UPDATE inventory SET stock = ?"
    args = (stock,)
    updated = run_sql(conn, "POST /api/admin/sync-stock", sql, args)
    return {"updated_rows": updated}


def place_order(conn, payload):
    """POST /api/orders - checkout. Idempotent on idem_key."""
    cid = int(payload["customer_id"])
    key = payload.get("idem_key") or uuid.uuid4().hex
    dup = conn.execute("SELECT id FROM orders WHERE idem_key=?", (key,)).fetchone()
    if dup:
        return {"order_id": dup["id"], "duplicate": True}
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute("INSERT INTO orders(customer_id,total_cents,status,idem_key,created_at) "
                           "VALUES(?,0,'paid',?,app_now())", (cid, key))
        oid, total = cur.lastrowid, 0
        for it in payload["items"]:
            row = conn.execute("SELECT price_cents FROM inventory WHERE sku=?", (it["sku"],)).fetchone()
            if not row:
                raise ValueError(f"unknown sku {it['sku']}")
            qty = int(it["qty"])
            total += row["price_cents"] * qty
            conn.execute("INSERT INTO order_items(order_id,sku,qty,unit_cents) VALUES(?,?,?,?)",
                         (oid, it["sku"], qty, row["price_cents"]))
            run_sql(conn, "POST /api/orders", "UPDATE inventory SET stock = MAX(stock - ?, 0) WHERE sku = ?",
                    (qty, it["sku"]))
        conn.execute("UPDATE orders SET total_cents=? WHERE id=?", (total, oid))
        conn.execute("COMMIT")
        return {"order_id": oid, "total_cents": total}
    except Exception:
        conn.execute("ROLLBACK")
        raise

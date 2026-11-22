import time

from . import db

SAMPLE_LIMIT = 20
UNSUPPORTED_CHECKSUM = "The HTTP recovery path exposes post-apply smoke checks; checksum verification is not available on this session."


def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _json_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, dict)):
        return value
    return str(value)


def _row(row_id, table, key, field, operation, before, after, note=None):
    return {
        "id": row_id,
        "table": table,
        "key": str(key),
        "field": field,
        "operation": operation,
        "before": _json_value(before),
        "after": _json_value(after),
        "note": note,
    }


def build_preview(conn, plan, summary, sample_limit=SAMPLE_LIMIT):
    current_stock = {row["sku"]: row["stock"] for row in conn.execute("SELECT sku, stock FROM inventory")}
    live_orders = {row["id"]: row["status"] for row in conn.execute("SELECT id, status FROM orders")}
    live_customers = {row["id"] for row in conn.execute("SELECT id FROM customers")}
    live_items = {row["id"] for row in conn.execute("SELECT id FROM order_items")}
    backorders = set(plan.get("backorder_ids") or ())

    rows = []
    counts = {"INSERT": 0, "UPDATE": 0, "DELETE": 0}
    by_table = {}

    def add(table, row, operation):
        rows.append(row)
        counts[operation] += 1
        entry = by_table.setdefault(table, {"INSERT": 0, "UPDATE": 0, "DELETE": 0})
        entry[operation] += 1

    for sku, name, target_stock, price_cents in plan.get("inventory_rows", ()):
        operation = "UPDATE" if sku in current_stock else "INSERT"
        add("inventory", _row(
            f"inventory:{sku}:stock", "inventory", sku, "stock", operation,
            current_stock.get(sku), target_stock,
            "Idempotent inventory upsert restores the pre-incident stock value."), operation)

    for order_id, customer_id, total_cents, status, idem_key, created_at in plan.get("order_rows", ()):
        if order_id in live_orders:
            if order_id in backorders and live_orders[order_id] != "backorder":
                add("orders", _row(
                    f"orders:{order_id}:status", "orders", order_id, "status", "UPDATE",
                    live_orders[order_id], "backorder",
                    "Oversell resolution marks the preserved order for ops follow-up."), "UPDATE")
        else:
            add("orders", _row(
                f"orders:{order_id}:record", "orders", order_id, "record", "INSERT", None,
                {"id": order_id, "customer_id": customer_id, "status": status,
                 "total_cents": total_cents},
                "Post-incident order re-asserted by the approved merge plan."), "INSERT")

    for item_id, order_id, sku, qty, unit_cents in plan.get("item_rows", ()):
        if item_id not in live_items:
            add("order_items", _row(
                f"order_items:{item_id}:record", "order_items", item_id, "record", "INSERT", None,
                {"id": item_id, "order_id": order_id, "sku": sku, "qty": qty},
                "Line item preserved with its parent order."), "INSERT")

    for customer_id, name, email in plan.get("customer_rows", ()):
        if customer_id not in live_customers:
            add("customers", _row(
                f"customers:{customer_id}:record", "customers", customer_id, "record", "INSERT", None,
                {"id": customer_id, "name": name},
                "Customer reference required by a preserved order; email is omitted."), "INSERT")

    ordered = sorted(rows, key=lambda item: (item["table"], item["key"], item["field"]))
    sampled = ordered[:max(0, int(sample_limit))]
    dry_run = summary.get("dry_run") or ()
    return {
        "label": "PROPOSED RECOVERY PROJECTION — NOT APPLIED",
        "generated_at": time.time(),
        "source": "Legacy merge plan plus read-only live database state",
        "row_count": len(rows),
        "rows": sampled,
        "sample_truncated": len(sampled) < len(rows),
        "tables": sorted(by_table),
        "operation_counts": counts,
        "counts_by_table": by_table,
        "delete_semantics": "The approved merge plan contains no DELETE statements; no deletions are proposed.",
        "conflicts": list(summary.get("conflicts") or ()),
        "validation": {
            "dry_run_ok": bool(summary.get("dry_run_ok")),
            "checks": [{"name": check.get("name"), "ok": bool(check.get("ok")),
                        "detail": check.get("detail")} for check in dry_run],
            "risk": summary.get("risk"),
        },
    }


def capture_actual(conn, preview):
    values = {}
    for row in (preview or {}).get("rows", ()):
        row_id = row.get("id")
        if not row_id:
            continue
        table = row.get("table")
        field = row.get("field")
        key = row.get("key")
        if table not in db.TABLES:
            values[row_id] = {"unavailable": "table is not part of the captured recovery scope"}
            continue
        primary_key = db.TABLES[table]
        record = conn.execute(
            f"SELECT * FROM {_quote(table)} WHERE {_quote(primary_key)} = ?", (key,)).fetchone()
        if record is None:
            values[row_id] = {"unavailable": "record is not present after recovery"}
            continue
        if field == "record" and isinstance(row.get("after"), dict):
            values[row_id] = {name: _json_value(record[name]) for name in row["after"] if name in record.keys()}
        elif field in record.keys():
            values[row_id] = _json_value(record[field])
        else:
            values[row_id] = {"unavailable": "field is not present after recovery"}
    return {
        "captured_at": time.time(),
        "source": "Live database read after the approved recovery committed",
        "values": values,
    }


def build_verification(checks, completed_at=None):
    reported = [{"name": check.get("name"), "ok": bool(check.get("ok")),
                 "detail": check.get("detail")} for check in (checks or ())]
    if reported:
        status = "passed" if all(check["ok"] for check in reported) else "failed"
    else:
        status = "unavailable"
    return {
        "status": status,
        "method": "Post-apply smoke checks recorded by the recovery engine",
        "checks": reported,
        "completed_at": time.time() if completed_at is None else completed_at,
        "checksum": {"status": "unavailable", "reason": UNSUPPORTED_CHECKSUM},
    }


def initial_undo_state():
    return {
        "available": False,
        "initiated": False,
        "succeeded": False,
        "failed": False,
        "detail": "Not started",
        "completed_at": None,
    }

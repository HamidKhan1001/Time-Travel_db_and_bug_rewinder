"""The five agent tools. Each is deterministic and independently testable.

  rewind_branch_tool      point-in-time branch of the DB
  extract_delta_tool      rows created after the rewind point
  plan_merge_tool         3-way merge plan + conflict/FK resolver + dry run
  diagnose_and_patch_tool root cause from query log → surgical patch, verified on a clone
  apply_recovery_tool     approved cutover with smoke checks (+ undo)

Supported crash scenarios
--------------------------
  Scenario 1 — stock wipe  : UPDATE inventory SET stock = ?         (sync_stock)
  Scenario 2 — price wipe  : UPDATE inventory SET price_cents = ?   (sync_price)

The patch/verify pipeline is data-driven via SCENARIO_REGISTRY so adding a
new scenario only requires registering its descriptor — no branching in the
tool code itself.
"""
import difflib
import os
import re
import time
from typing import Any

from . import appcode, db, guard, llm

INV_UPSERT = ("INSERT INTO inventory(sku,name,stock,price_cents) VALUES(?,?,?,?) "
              "ON CONFLICT(sku) DO UPDATE SET stock=excluded.stock, price_cents=excluded.price_cents")
CUST_SQL = "INSERT INTO customers(id,name,email) VALUES(?,?,?) ON CONFLICT(id) DO NOTHING"
ORDER_SQL = ("INSERT INTO orders(id,customer_id,total_cents,status,idem_key,created_at) VALUES(?,?,?,?,?,?) "
             "ON CONFLICT(id) DO NOTHING")
ITEM_SQL = ("INSERT INTO order_items(id,order_id,sku,qty,unit_cents) VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO NOTHING")
BACKORDER_SQL = "UPDATE orders SET status='backorder' WHERE id=?"
STATEMENTS = [INV_UPSERT, CUST_SQL, ORDER_SQL, ITEM_SQL, BACKORDER_SQL]


# ---------------------------------------------------------------- incident detection
def detect_incident(live):
    """Latest unscoped mass-write in the query log, with its scenario metadata.

    Returns a dict augmented with a 'scenario' key so callers can tell which
    crash happened without re-inspecting the SQL themselves.
    """
    for r in live.execute("SELECT * FROM query_log WHERE rows_affected > 25 ORDER BY ts DESC"):
        if guard.is_unscoped(r["sql"]):
            row = dict(r)
            row["scenario"] = _detect_scenario(row["sql"])
            return row
    return None


def _detect_scenario(sql: str) -> str:
    """Classify an unscoped SQL statement into a named crash scenario.

    Returns a stable string key understood by the UI and patch registry.
    New scenarios: add an elif branch here and register in SCENARIO_REGISTRY.
    """
    sql_upper = sql.upper()
    if "PRICE_CENTS" in sql_upper:
        return "price_wipe"
    if "STOCK" in sql_upper:
        return "stock_wipe"
    return "unknown"


# ---------------------------------------------------------------- 1. rewind
def rewind_branch_tool(live, target_ts, branch_path):
    t0 = time.perf_counter()
    events = db.changes_after(live, target_ts)          # newest first
    branch = db.clone(live, branch_path)
    branch.execute("BEGIN")
    db.reverse_changes(branch, target_ts, events)
    branch.execute("COMMIT")
    row = branch.execute("SELECT COUNT(*) n, SUM(stock) u, SUM(stock=0) z FROM inventory").fetchone()
    return branch, {"events_reversed": len(events), "inventory_rows": row["n"], "units": row["u"],
                    "zero_rows": row["z"], "ms": round((time.perf_counter() - t0) * 1000, 1)}


# ---------------------------------------------------------------- 2. delta
def extract_delta_tool(live, target_ts, incident_ts):
    orders = [dict(r) for r in live.execute("SELECT * FROM orders WHERE created_at > ? ORDER BY id", (target_ts,))]
    ids = [o["id"] for o in orders]
    items = [dict(r) for r in live.execute(
        f"SELECT * FROM order_items WHERE order_id IN ({','.join('?' * len(ids))}) ORDER BY id", ids)] if ids else []
    cust_ids = sorted({o["customer_id"] for o in orders})
    customers = [dict(r) for r in live.execute(
        f"SELECT * FROM customers WHERE id IN ({','.join('?' * len(cust_ids))})", cust_ids)] if cust_ids else []
    for o in orders:
        o["phase"] = "post-crash" if incident_ts and o["created_at"] >= incident_ts else "pre-crash"
        o["items"] = [i for i in items if i["order_id"] == o["id"]]
    return {"orders": orders, "items": items, "customers": customers,
            "post_crash": sum(o["phase"] == "post-crash" for o in orders),
            "pre_crash": sum(o["phase"] == "pre-crash" for o in orders)}


# ---------------------------------------------------------------- 3. checks + merge
def run_checks(conn, expected_stock, preserved_ids):
    out = []
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    out.append({"name": "Foreign keys intact", "ok": not fk, "detail": f"{len(fk)} violations"})
    neg = conn.execute("SELECT COUNT(*) FROM inventory WHERE stock < 0").fetchone()[0]
    out.append({"name": "No negative stock", "ok": neg == 0, "detail": f"{neg} negative rows"})
    neg_p = conn.execute("SELECT COUNT(*) FROM inventory WHERE price_cents <= 0").fetchone()[0]
    out.append({"name": "No zero or negative prices", "ok": neg_p == 0, "detail": f"{neg_p} zero/negative rows"})
    got = {r["sku"]: r["stock"] for r in conn.execute("SELECT sku, stock FROM inventory")}
    bad = sum(1 for s, v in expected_stock.items() if got.get(s) != v)
    out.append({"name": "Inventory matches merge plan", "ok": bad == 0, "detail": f"{bad} mismatched SKUs"})
    present = conn.execute(
        f"SELECT COUNT(*) FROM orders WHERE id IN ({','.join('?' * len(preserved_ids))})", preserved_ids
    ).fetchone()[0] if preserved_ids else 0
    out.append({"name": "Post-incident orders preserved", "ok": present == len(preserved_ids),
                "detail": f"{present}/{len(preserved_ids)} present"})
    return out


def execute_plan(conn, plan):
    """Apply a plan inside the caller's transaction. Every statement goes through the guard first."""
    for s in STATEMENTS:
        v = guard.analyze(s)
        if not v["allowed"]:
            raise RuntimeError(f"Guardrail blocked statement: {v['why']}")
    conn.executemany(INV_UPSERT, plan["inventory_rows"])
    conn.executemany(CUST_SQL, plan["customer_rows"])
    conn.executemany(ORDER_SQL, plan["order_rows"])
    conn.executemany(ITEM_SQL, plan["item_rows"])
    conn.executemany(BACKORDER_SQL, [(i,) for i in plan["backorder_ids"]])


def plan_merge_tool(live, branch, delta, scratch_path):
    base = {r["sku"]: dict(r) for r in branch.execute("SELECT * FROM inventory")}
    cur = {r["sku"]: dict(r) for r in live.execute("SELECT * FROM inventory")}
    base_orders = {r["id"]: dict(r) for r in branch.execute("SELECT * FROM orders")}
    base_idem = {r["idem_key"] for r in base_orders.values()}
    base_cust = {r["id"] for r in branch.execute("SELECT id FROM customers")}

    # --- Conflict & foreign-key resolver
    running = {s: v["stock"] for s, v in base.items()}
    conflicts, checks = [], {"fk_customer": 0, "fk_sku": 0, "idem_unique": 0, "id_collision": 0}
    backorder_ids, seen_idem = [], set()
    for o in delta["orders"]:
        if o["customer_id"] in base_cust or any(c["id"] == o["customer_id"] for c in delta["customers"]):
            checks["fk_customer"] += 1
        if o["id"] in base_orders:
            conflicts.append({"kind": "id-collision", "order_id": o["id"],
                              "detail": f"Order id {o['id']} already exists in the rewound state."})
        else:
            checks["id_collision"] += 1
        if o["idem_key"] in base_idem or o["idem_key"] in seen_idem:
            conflicts.append({"kind": "duplicate-idempotency-key", "order_id": o["id"],
                              "detail": f"Idempotency key {o['idem_key'][:10]} already used."})
        else:
            checks["idem_unique"] += 1
        seen_idem.add(o["idem_key"])
        for it in o["items"]:
            if it["sku"] not in base and it["sku"] not in cur:
                conflicts.append({"kind": "orphan-sku", "order_id": o["id"], "detail": f"Unknown SKU {it['sku']}"})
                continue
            checks["fk_sku"] += 1
            if it["sku"] not in running:
                continue
            if running[it["sku"]] >= it["qty"]:
                running[it["sku"]] -= it["qty"]
            else:
                short = it["qty"] - running[it["sku"]]
                running[it["sku"]] = 0
                conflicts.append({
                    "kind": "oversell", "order_id": o["id"], "sku": it["sku"], "shortfall": short,
                    "detail": f"Order #{o['id']} bought {it['qty']}x {it['sku']} but only "
                              f"{it['qty'] - short} existed at the rewind point. Resolved: stock clamped to 0, "
                              f"order kept and marked 'backorder' for ops follow-up ({short} unit(s) owed)."})
                if o["id"] not in backorder_ids:
                    backorder_ids.append(o["id"])
    expected = running
    llm.explain_conflicts(conflicts)
    inv_rows = [(s, base[s]["name"], expected[s], base[s]["price_cents"])
                for s in sorted(expected)
                if cur.get(s, {}).get("stock") != expected[s] or cur.get(s, {}).get("price_cents") != base[s]["price_cents"]]
    plan = {
        "inventory_rows": inv_rows,
        "customer_rows": [(c["id"], c["name"], c["email"]) for c in delta["customers"]],
        "order_rows": [(o["id"], o["customer_id"], o["total_cents"], o["status"], o["idem_key"], o["created_at"])
                       for o in delta["orders"]],
        "item_rows": [(i["id"], i["order_id"], i["sku"], i["qty"], i["unit_cents"]) for i in delta["items"]],
        "backorder_ids": backorder_ids,
    }
    # --- dry run on a scratch clone of live: nothing touches production until approval
    scratch = db.clone(live, scratch_path)
    scratch.execute("BEGIN")
    execute_plan(scratch, plan)
    dry = run_checks(scratch, expected, [o["id"] for o in delta["orders"]])
    scratch.execute("ROLLBACK")
    scratch.close()
    os.remove(scratch_path)

    verdicts = [guard.analyze(s) for s in STATEMENTS]
    units_before = sum(v["stock"] for v in cur.values())
    units_after = sum(expected.values())
    zero_before = sum(1 for v in cur.values() if v["stock"] == 0)
    n_orders = len(delta["orders"])
    factors = [("Base risk (scoped, idempotent statements, dry-run on clone)", 8)]
    if conflicts:
        factors.append((f"{len(conflicts)} data conflict(s) auto-resolved, needs human eyes", 12 * len(conflicts)))
    if len(inv_rows) > 1000:
        factors.append((f"Large blast radius ({len(inv_rows):,} rows)", 5))
    if not all(c["ok"] for c in dry):
        factors.append(("Dry-run check FAILED", 60))
    score = min(100, sum(f[1] for f in factors))
    sample = inv_rows[:3]
    preview = [
        f"-- Restore inventory ({len(inv_rows):,} rows, idempotent upsert)\n{INV_UPSERT};",
        "-- e.g. " + "; ".join(f"({r[0]}, stock={r[2]})" for r in sample) + f"; ... +{max(0, len(inv_rows) - 3):,} more",
        f"-- Re-assert {n_orders} post-incident orders (no-op if present)\n{ORDER_SQL};",
        f"-- Resolve oversell conflicts ({len(backorder_ids)})\n{BACKORDER_SQL};" if backorder_ids else
        "-- No oversell conflicts to resolve",
    ]
    summary = {
        "restored_rows": len(inv_rows), "orders_preserved": n_orders,
        "order_ids": [o["id"] for o in delta["orders"]],
        "units_before": units_before, "units_after": units_after,
        "zero_before": zero_before, "zero_after": sum(1 for v in expected.values() if v == 0),
        "conflicts": conflicts, "resolver_checks": checks,
        "dry_run": dry, "dry_run_ok": all(c["ok"] for c in dry),
        "guardrails": [{"allowed": v["allowed"], "rule": v["rule"], "sql": v["sql"]} for v in verdicts],
        "risk": {"score": score, "label": "LOW" if score < 25 else "MEDIUM" if score < 60 else "HIGH",
                 "factors": factors},
        "preview_sql": preview,
        "live_marker": live.execute("SELECT COALESCE(MAX(id),0) FROM changelog").fetchone()[0],
    }
    return plan, expected, summary


# ---------------------------------------------------------------- 4. diagnose + patch
SCENARIO_REGISTRY = {
    "stock_wipe": {
        "sql_fragment": "UPDATE inventory SET stock = ?",
        "fn_name": "sync_stock",
        "col": "stock",
        "endpoint": "POST /api/admin/sync-stock",
        "test_payload": {"sku": "APX-0007", "stock": 0},
        "test_missing": {"stock": 0},
        "test_name": "Crash payload {sku: APX-0007} touches exactly 1 row",
    },
    "price_wipe": {
        "sql_fragment": "UPDATE inventory SET price_cents = ?",
        "fn_name": "sync_price",
        "col": "price_cents",
        "endpoint": "POST /api/admin/sync-price",
        "test_payload": {"sku": "APX-0042", "price_cents": 19900},
        "test_missing": {"price_cents": 19900},
        "test_name": "Crash payload {sku: APX-0042} touches exactly 1 row",
    },
}


def _patch_source_for_scenario(src: str, scenario: dict) -> str | None:
    bad_sql = scenario["sql_fragment"]
    fn_name = scenario["fn_name"]
    col = scenario["col"]
    lines = src.split("\n")

    in_fn = False
    idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith(f"def {fn_name}("):
            in_fn = True
        elif in_fn and line.startswith("def "):
            break
        if in_fn and f'"{bad_sql}"' in line and line.strip().startswith("sql"):
            idx = i
            break

    if idx is None:
        return None

    ind_match = re.match(r"\s*", lines[idx])
    ind = ind_match.group(0) if ind_match else ""
    aidx = next((j for j in range(idx + 1, min(idx + 5, len(lines)))
                 if re.match(r"\s*args\s*=\s*\(", lines[j])), None)
    if aidx is None:
        return None

    arg_match = re.search(r"\((.*?),?\)", lines[aidx])
    if arg_match is None:
        return None
    arg_names = arg_match.group(1)
    lines[idx] = f'{ind}sql = "{bad_sql} WHERE sku = ?"'
    lines[aidx] = f"{ind}args = ({arg_names}, sku)"
    lines[idx:idx] = [
        f"{ind}if not sku:",
        f'{ind}    raise ValueError("sku is required: refusing unscoped {col} update")',
    ]
    return "\n".join(lines)


def _verify_patch_candidate(candidate_src: str, scenario: dict, branch) -> tuple[bool, list[dict]]:
    fn_name = scenario["fn_name"]
    col = scenario["col"]
    try:
        ns: dict[str, Any] = {}
        exec(compile(candidate_src, "patched_handlers", "exec"), ns)
        sandbox = db.clone(branch, ":memory:")
        before = {r["sku"]: r[col] for r in sandbox.execute(f"SELECT sku, {col} FROM inventory")}
        res = ns[fn_name](sandbox, scenario["test_payload"])
        after = {r["sku"]: r[col] for r in sandbox.execute(f"SELECT sku, {col} FROM inventory")}
        changed = [s for s in before if before[s] != after[s]]
        try:
            ns[fn_name](sandbox, scenario["test_missing"])
            rejects_missing = False
        except ValueError:
            rejects_missing = True
        sandbox.close()

        expected_sku = scenario["test_payload"]["sku"]
        t_list = [
            {"name": scenario["test_name"],
             "ok": res.get("updated_rows") == 1 and changed == [expected_sku],
             "detail": f"{res.get('updated_rows')} row(s) updated"},
            {"name": "Payload without sku is rejected", "ok": rejects_missing, "detail": "ValueError raised"},
        ]
        return all(t["ok"] for t in t_list), t_list
    except Exception as e:
        return False, [{"name": "Patch execution on sandbox clone", "ok": False, "detail": str(e)}]


def diagnose_and_patch_tool(live, branch, incident):
    if not incident:
        return {"found": False, "explanation": "No unscoped mass-write found in the query log."}
    src = appcode.read_source()
    scenario_key = incident.get("scenario", _detect_scenario(incident["sql"]))
    scenario = SCENARIO_REGISTRY.get(scenario_key, SCENARIO_REGISTRY["stock_wipe"])

    out = {"found": True, "incident_sql": incident["sql"], "source": incident["source"],
           "rows_affected": incident["rows_affected"], "at": incident["ts"],
           "scenario": scenario_key,
           "guard_verdict": guard.analyze(incident["sql"])}

    # --- LLM patch attempt (primary) ---
    patched = None
    llm_patch = llm.propose_patch(
        source=src,
        incident_sql=incident["sql"],
        rows_affected=incident["rows_affected"],
        endpoint=incident["source"],
    )
    if llm_patch is not None:
        patched = llm_patch.patched_source
        out["patch_source"] = "llm"
        out["_llm_explanation"] = llm_patch.explanation
    else:
        patched = _patch_source_for_scenario(src, scenario)
        out["patch_source"] = "regex"

    if not patched:
        out["explanation"] = f"Offending query located in the log but no safe automatic patch available for {scenario_key}."
        out["patch_ok"] = False
        return out

    patch_ok, tests = _verify_patch_candidate(patched, scenario, branch)
    # If LLM patch failed sandbox verification, fall back to deterministic regex patch
    if not patch_ok and out.get("patch_source") == "llm":
        fallback_patched = _patch_source_for_scenario(src, scenario)
        if fallback_patched:
            fb_ok, fb_tests = _verify_patch_candidate(fallback_patched, scenario, branch)
            if fb_ok:
                patched = fallback_patched
                patch_ok, tests = fb_ok, fb_tests
                out["patch_source"] = "regex (fallback)"
                out.pop("_llm_explanation", None)

    diff = "".join(difflib.unified_diff(src.splitlines(True), patched.splitlines(True),
                                         "a/app/handlers.py", "b/app/handlers.py"))

    col_name = scenario["col"]
    out.update({
        "patch_ok": patch_ok, "diff": diff, "patched_source": patched, "tests": tests,
        "explanation": out.pop("_llm_explanation", None) or (
            f"The endpoint ({incident['source']}) ran `{incident['sql']}` with no WHERE clause. "
            f"It was meant to set {col_name} for one SKU, but it overwrote {col_name} on all "
            f"{incident['rows_affected']:,} rows. The fix scopes the UPDATE to "
            f"`WHERE sku = ?` and rejects requests that omit the SKU."
        ),
    })
    return out


# ---------------------------------------------------------------- 5. apply + undo
def apply_recovery_tool(live, plan, expected, preserved_ids, marker, patched_source, backup_db, backup_src, timing=None):
    """Approved cutover. Atomic: either every check passes and we commit, or nothing changes."""
    cur_marker = live.execute("SELECT COALESCE(MAX(id),0) FROM changelog").fetchone()[0]
    if cur_marker != marker:
        raise RuntimeError("Plan is stale: live data changed since the plan was built. Re-run the rewind.")
    snap = db.clone(live, backup_db)
    snap.close()
    with open(backup_src, "w") as f:
        f.write(appcode.read_source())
    live.execute("BEGIN IMMEDIATE")
    try:
        execute_plan(live, plan)
        verification_started = time.perf_counter()
        checks = run_checks(live, expected, preserved_ids)
        if timing is not None:
            timing["verification_seconds"] = time.perf_counter() - verification_started
        if not all(c["ok"] for c in checks):
            raise RuntimeError("Post-apply smoke checks failed: " + "; ".join(c["name"] for c in checks if not c["ok"]))
        live.execute("COMMIT")
    except Exception:
        live.execute("ROLLBACK")
        raise
    if patched_source:
        appcode.write_source(patched_source)
    return checks


def undo_recovery(live, backup_db, backup_src):
    """Rewind the rewind: restore the pre-recovery snapshot and the original code."""
    snap = db.connect(backup_db)
    snap.backup(live)
    snap.close()
    with open(backup_src, "r", encoding="utf-8") as handle:
        appcode.write_source(handle.read())

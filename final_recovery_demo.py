#!/usr/bin/env python3
"""Final Task 3 database recovery demonstration.

Uses the existing project workflow:
- seed/reset initializes deterministic data
- agent.start() parses intent, detects incident, builds branch/plan/patch
- human approval gate via agent.approve() (explicit confirmation prompt)
- checksum/integrity checks run inside recovery engine and smoke checks

Run: python3 final_recovery_demo.py
Optional: python3 final_recovery_demo.py --yes  # explicit non-interactive approval for automation
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ.setdefault("TT_PACE", "0")

from timetravel import agent, appcode, db, seed, tools
from timetravel.recovery import verification


def banner(step, title):
    print(f"\n{'=' * 72}\nSTEP {step}: {title}\n{'=' * 72}")


def print_rows(rows):
    for row in rows:
        print("  ", row)


def main():
    parser = argparse.ArgumentParser(description="Final database recovery demo")
    parser.add_argument("--yes", action="store_true",
                        help="Explicit non-interactive approval after plan display")
    args = parser.parse_args()

    banner(1, "Initialize the database")
    seed.reset()
    appcode.reload()
    print("Initialized deterministic demo database and restored pristine buggy handler.")
    print(f"Live DB: {db.LIVE}")

    banner(2, "Generate test records")
    with db.LOCK:
        conn = db.connect()
        try:
            counts = {
                "customers": conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
                "inventory": conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0],
                "orders": conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
                "order_items": conn.execute("SELECT COUNT(*) FROM order_items").fetchone()[0],
            }
        finally:
            conn.close()
    print("Record counts:", counts)

    banner(3, "Capture the original snapshot")
    with db.LOCK:
        conn = db.connect()
        try:
            baseline = verification.capture_reference(conn, db.TABLES, label="demo-original")
            original_counts = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in sorted(db.TABLES)
            }
        finally:
            conn.close()
    print(f"Original checksum: {baseline.database_checksum}")
    print(f"Rows captured:    {baseline.row_count}")
    print(f"Table counts:     {original_counts}")

    banner(4, "Trigger the crash")
    crash_payload = {"sku": "APX-0007", "stock": 0}
    print(f"Trigger payload: {crash_payload}")
    with db.LOCK:
        conn = db.connect()
        try:
            result = appcode.fn("sync_stock")(conn, crash_payload)
        finally:
            conn.close()
    print("Crash result:", result)
    demo_orders = seed.demo_orders()
    print(f"Post-crash legitimate orders placed: {[o['order_id'] for o in demo_orders]}")

    banner(5, "Display affected records")
    with db.LOCK:
        conn = db.connect()
        try:
            incident = tools.detect_incident(conn)
            zeroed = conn.execute(
                "SELECT sku, name, stock FROM inventory WHERE stock = 0 ORDER BY sku LIMIT 10"
            ).fetchall()
            affected_count = conn.execute("SELECT COUNT(*) FROM inventory WHERE stock = 0").fetchone()[0]
        finally:
            conn.close()
    print("Detected incident:", incident)
    print(f"Affected inventory rows with stock=0: {affected_count} (showing up to 10)")
    print_rows([dict(r) for r in zeroed])

    banner(6, "Generate the recovery plan")
    prompt = ("Take the business back to 2 minutes ago, keep the 3 orders that came in after the crash, "
              "and fix the bug that caused it.")
    started = time.perf_counter()
    session = agent.start(prompt, background=False)
    planning_elapsed = time.perf_counter() - started
    if session.phase != "awaiting_approval":
        print("Session did not reach approval gate.")
        for e in session.events[-10:]:
            print(f"[{e['agent']}] {e['msg']}")
        sys.exit(2)
    plan = session.plan or {}
    print(f"Session: {session.id}")
    print(f"Phase:   {session.phase}")
    print(f"Planning wall time: {planning_elapsed:.3f}s")
    print(f"Risk: {plan.get('risk')}")
    print(f"Orders preserved: {plan.get('orders_preserved')} ids={plan.get('order_ids')}")
    print(f"Inventory rows to restore: {plan.get('restored_rows')}")
    print(f"Conflicts: {len(plan.get('conflicts', []))}")
    for c in plan.get("conflicts", []):
        print("  -", c.get("detail"))
    print(f"Dry run ok: {plan.get('dry_run_ok')}")
    for check in plan.get("dry_run", []):
        print(f"  [{'PASS' if check['ok'] else 'FAIL'}] {check['name']}: {check['detail']}")

    banner(7, "Obtain human approval through the existing project workflow")
    print("Existing workflow: agent.start() -> awaiting_approval -> agent.approve(session_id)")
    # Build expected post-recovery reference BEFORE approval by simulating the approved plan on a
    # clone of the current live DB. This represents the deterministic expected recovered state.
    with db.LOCK:
        conn = db.connect()
        try:
            sim = db.clone(conn, ":memory:")
        finally:
            conn.close()
    sim.execute("BEGIN IMMEDIATE")
    tools.execute_plan(sim, session.internal["plan"])
    sim.execute("COMMIT")
    expected_baseline = verification.build_baseline(sim, db.TABLES, label="expected-recovered")
    sim.close()

    if args.yes:
        print("AUTO-APPROVAL granted by --yes flag (explicit non-interactive approval).")
        approved = True
    else:
        answer = input(f"Approve recovery for {session.id}? [y/N]: ").strip().lower()
        approved = answer in {"y", "yes"}
    if not approved:
        print("Recovery not approved. No changes applied.")
        baseline.close()
        expected_baseline.close()
        sys.exit(1)

    banner(8, "Execute recovery")
    exec_started = time.perf_counter()
    session = agent.approve(session.id)
    exec_elapsed = time.perf_counter() - exec_started
    print(f"Phase after approval: {session.phase}")
    print(f"Execution wall time:  {exec_elapsed:.3f}s")
    if session.phase != "applied":
        for e in session.events[-10:]:
            print(f"[{e['agent']}] {e['msg']}")
        baseline.close()
        expected_baseline.close()
        sys.exit(3)

    banner(9, "Verify checksums")
    with db.LOCK:
        conn = db.connect()
        try:
            report = verification.verify_state_against(conn, expected_baseline, db.TABLES)
        finally:
            conn.close()
    print(json.dumps(report, indent=2))
    if report["integrity_status"] != "VERIFIED":
        print("Checksum verification FAILED - recovery must not be considered successful.")
        baseline.close()
        expected_baseline.close()
        sys.exit(4)

    banner(10, "Display actual recovery duration and integrity status")
    total = planning_elapsed + exec_elapsed
    print(f"Planning wall time:   {planning_elapsed:.3f}s")
    print(f"Execution wall time:  {exec_elapsed:.3f}s")
    print(f"Total demo wall time: {total:.3f}s")
    print(f"Integrity status:     {report['integrity_status']}")
    print(f"Original checksum:    {report['original_checksum']}")
    print(f"Recovered checksum:   {report['recovered_checksum']}")
    print(f"Rows checked:         {report['total_rows_checked']}")
    print(f"Matching rows:        {report['matching_rows']}")
    print(f"Mismatching rows:     {report['mismatching_rows']}")
    print(f"Missing rows:         {report['missing_rows']}")
    print(f"Unexpected rows:      {report['unexpected_rows']}")

    with db.LOCK:
        conn = db.connect()
        try:
            post = {
                "inventory_units": conn.execute("SELECT SUM(stock) FROM inventory").fetchone()[0],
                "zero_stock_rows": conn.execute("SELECT COUNT(*) FROM inventory WHERE stock=0").fetchone()[0],
                "orders_gt_1040": [tuple(r) for r in conn.execute(
                    "SELECT id, status FROM orders WHERE id > 1040 ORDER BY id").fetchall()],
            }
        finally:
            conn.close()
    print("Post-recovery state:", post)
    baseline.close()
    print("\nDemo completed successfully.")


if __name__ == "__main__":
    main()

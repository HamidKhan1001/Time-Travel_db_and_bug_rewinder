import argparse
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from setup_second_crash import (
    FAULTY_SQL,
    INTENDED_ORDER_ID,
    LEGITIMATE_ORDER_ID,
    REPORT_FILE,
    SCENARIO,
    STATE_FILE,
    prepare_directory,
    setup_scenario,
    table_rows,
)
from timetravel import db
from timetravel.recovery import (
    change_tracker,
    explain_plan,
    inspect_foreign_keys,
    integrity,
    recovery_engine,
)


def load_state(state_path):
    with open(state_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _order_rows(conn):
    return [dict(row) for row in conn.execute("SELECT * FROM orders ORDER BY id")]


def _failed_checks(checks):
    return [check for check in checks if not check["ok"]]


def _normalize_state(value):
    if isinstance(value, float):
        return float(format(value, ".15g"))
    if isinstance(value, list):
        return [_normalize_state(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_state(item) for key, item in value.items()}
    return value


def _states_match(left, right):
    return _normalize_state(left) == _normalize_state(right)


def run_scenario(directory=None, state_path=None):
    """Run the isolated faulty UPDATE and recover it with the shared recovery engine."""
    if state_path is None:
        directory = prepare_directory(directory)
        state_path = os.path.join(directory, STATE_FILE)
        if not os.path.exists(state_path):
            setup_scenario(directory)
        state = load_state(state_path)
    else:
        state = load_state(state_path)
        directory = os.path.dirname(os.path.abspath(state_path))

    report_path = os.path.join(directory, REPORT_FILE)
    conn = db.connect(state["db_path"])
    try:
        if integrity.checksum(conn, db.TABLES) != state["original_checksum"]:
            raise RuntimeError("captured original checksum no longer matches the isolated database")
        if not _states_match(table_rows(conn), state["original_tables"]):
            raise RuntimeError("captured original table state no longer matches the isolated database")

        cursor = conn.execute(FAULTY_SQL)
        faulty_rowcount = cursor.rowcount
        events = change_tracker.fetch_events(conn, after_event_id=state["anchor_event_id"], order="id ASC")
        faulty_events = [event for event in events if event.tbl == "orders" and event.op == "U"]
        if not faulty_events:
            raise RuntimeError("faulty UPDATE produced no captured order UPDATE events")
        faulty_txn = faulty_events[0].transaction_id
        if any(event.transaction_id != faulty_txn for event in faulty_events):
            raise RuntimeError("faulty UPDATE events are split across multiple transactions")
        affected = [{
            "event_id": event.id,
            "transaction_id": event.transaction_id,
            "order_id": event.pk,
            "before_status": json.loads(event.old_values)["status"],
            "after_status": json.loads(event.new_values)["status"],
        } for event in faulty_events]
        after_fault_checksum = integrity.checksum(conn, db.TABLES)

        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO orders(id, customer_id, total_cents, status, idem_key, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (LEGITIMATE_ORDER_ID, 1, 525, "paid", "second-legitimate-2005", db.clock.now()))
        conn.execute("COMMIT")
        events = change_tracker.fetch_events(conn, after_event_id=state["anchor_event_id"], order="id ASC")
        legitimate_txn = events[-1].transaction_id
        if legitimate_txn == faulty_txn:
            raise RuntimeError("legitimate transaction was not isolated from the faulty transaction")

        plan = recovery_engine.create_plan(conn, tables=db.TABLES,
                                           anchor_event_id=state["anchor_event_id"],
                                           transaction_ids=[faulty_txn])
        result = recovery_engine.execute_plan(conn, plan, tables=db.TABLES)

        final_tables = table_rows(conn)
        final_orders = _order_rows(conn)
        original_orders = state["original_tables"]["orders"]
        expected_statuses = {row["id"]: row["status"] for row in original_orders}
        actual_statuses = {row["id"]: row["status"] for row in final_orders}
        restored = all(actual_statuses.get(order_id) == status
                       for order_id, status in expected_statuses.items())
        legit_order = next((row for row in final_orders if row["id"] == LEGITIMATE_ORDER_ID), None)
        legit_preserved = legit_order is not None and legit_order["status"] == "paid"
        expected_tables = copy.deepcopy(state["original_tables"])
        expected_tables["orders"].append(legit_order)
        expected_tables["orders"].sort(key=lambda row: row["id"])
        state_matches = _states_match(final_tables, expected_tables)

        keys = inspect_foreign_keys(conn, db.TABLES)
        fk_checks = integrity.verify_foreign_keys(conn, keys)
        failed = _failed_checks(result["checks"]) + _failed_checks(fk_checks)
        passed = not failed and restored and legit_preserved and state_matches
        report = {
            "status": "PASS" if passed else "FAIL",
            "scenario": SCENARIO,
            "db_path": state["db_path"],
            "state_path": state["state_path"],
            "report_path": report_path,
            "anchor_event_id": state["anchor_event_id"],
            "faulty_sql": FAULTY_SQL,
            "intended_order_id": INTENDED_ORDER_ID,
            "faulty_transaction_id": faulty_txn,
            "faulty_rowcount": faulty_rowcount,
            "affected_count": len(affected),
            "affected_tables": sorted({event.tbl for event in faulty_events}),
            "affected_records": affected,
            "legitimate_transaction_id": legitimate_txn,
            "legitimate_order": legit_order,
            "plan": explain_plan(plan),
            "recovery": {
                "audit_run_id": result["audit_run_id"],
                "steps_applied": result["steps_applied"],
                "fingerprint": result["fingerprint"],
                "execution_order": result["execution_order"],
            },
            "checksums": {
                "original": state["original_checksum"],
                "after_fault": after_fault_checksum,
                "final": integrity.checksum(conn, db.TABLES),
            },
            "verification": {
                "checksum_verification": result["verification"],
                "integrity_status": result["verification"]["integrity_status"],
                "engine_checks_ok": not _failed_checks(result["checks"]),
                "foreign_keys_ok": not _failed_checks(fk_checks),
                "original_statuses_restored": restored,
                "legitimate_order_preserved": legit_preserved,
                "state_matches_expected": state_matches,
                "failed_checks": failed,
                "foreign_key_checks": fk_checks,
            },
            "final_orders": final_orders,
        }
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
        if not passed:
            raise RuntimeError(f"second crash verification failed; see {report_path}")
        return report
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Run and recover the isolated second crash scenario.")
    parser.add_argument("--dir", help="Directory containing second_crash_state.json")
    parser.add_argument("--state", help="Exact path to second_crash_state.json")
    args = parser.parse_args()
    report = run_scenario(directory=args.dir, state_path=args.state)
    print(json.dumps({
        "status": report["status"],
        "scenario": report["scenario"],
        "report_path": report["report_path"],
        "affected_count": report["affected_count"],
        "legitimate_order_preserved": report["verification"]["legitimate_order_preserved"],
        "foreign_keys_ok": report["verification"]["foreign_keys_ok"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

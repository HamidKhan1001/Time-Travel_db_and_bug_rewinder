import argparse
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from timetravel import db
from timetravel.recovery import change_tracker, integrity

DB_FILE = "second_crash.db"
STATE_FILE = "second_crash_state.json"
REPORT_FILE = "second_crash_report.json"
SCENARIO = "orders-status-unscoped-update"
FAULTY_SQL = "UPDATE orders SET status = 'cancelled'"
INTENDED_ORDER_ID = 2004
LEGITIMATE_ORDER_ID = 2005
SEED_CUSTOMERS = ((1, "Ada", "ada@example.com"), (2, "Grace", "grace@example.com"))
SEED_ORDERS = (
    (2001, 1, 1500, "paid", "second-2001"),
    (2002, 2, 2750, "pending", "second-2002"),
    (2003, 1, 900, "shipped", "second-2003"),
    (2004, 2, 4100, "paid", "second-2004"),
)


def prepare_directory(directory=None):
    if directory is None:
        return tempfile.mkdtemp(prefix="tt-second-crash-")
    os.makedirs(directory, exist_ok=True)
    return os.path.abspath(directory)


def table_rows(conn, tables=None):
    tables = tables or db.TABLES
    rows = {}
    for table, pk in sorted(tables.items()):
        rows[table] = [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY {pk}")]
    return rows


def setup_scenario(directory=None):
    """Create an isolated DB, seed fixed data, and persist the original state."""
    directory = prepare_directory(directory)
    db_path = os.path.join(directory, DB_FILE)
    state_path = os.path.join(directory, STATE_FILE)
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = db.connect(db_path)
    try:
        db.create_schema(conn)
        for customer_id, name, email in SEED_CUSTOMERS:
            conn.execute("INSERT INTO customers(id, name, email) VALUES(?, ?, ?)",
                         (customer_id, name, email))
        for order_id, customer_id, total, status, idem in SEED_ORDERS:
            conn.execute(
                "INSERT INTO orders(id, customer_id, total_cents, status, idem_key, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (order_id, customer_id, total, status, idem, db.clock.now()))
        anchor = change_tracker.latest_event_id(conn)
        state = {
            "scenario": SCENARIO,
            "db_path": db_path,
            "state_path": state_path,
            "anchor_event_id": anchor,
            "faulty_sql": FAULTY_SQL,
            "intended_order_id": INTENDED_ORDER_ID,
            "original_checksum": integrity.checksum(conn, db.TABLES),
            "original_tables": table_rows(conn),
        }
        with open(state_path, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
        return state
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Set up the isolated second crash scenario.")
    parser.add_argument("--dir", help="Directory for second_crash.db and second_crash_state.json")
    args = parser.parse_args()
    state = setup_scenario(args.dir)
    print(json.dumps({
        "db_path": state["db_path"],
        "state_path": state["state_path"],
        "anchor_event_id": state["anchor_event_id"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

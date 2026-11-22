import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from run_second_crash import run_scenario
from setup_second_crash import setup_scenario
from timetravel import db
from timetravel.recovery import (
    change_tracker,
    inspect_foreign_keys,
    integrity,
    recovery_engine,
)


class SecondCrashScenarioTests(unittest.TestCase):
    def setUp(self):
        db.clock.offset = 0
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        db.clock.offset = 0
        self.tmp.cleanup()

    def assert_checks_ok(self, checks):
        self.assertEqual([check for check in checks if not check["ok"]], [])

    def test_orders_status_crash_scenario(self):
        state = setup_scenario(self.tmp.name)
        report = run_scenario(directory=self.tmp.name)

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["scenario"], "orders-status-unscoped-update")
        self.assertEqual(report["faulty_sql"], "UPDATE orders SET status = 'cancelled'")
        self.assertEqual(report["faulty_rowcount"], 4)
        self.assertEqual(report["affected_count"], 4)
        self.assertEqual(report["affected_tables"], ["orders"])
        self.assertEqual(report["plan"]["selected_transaction_ids"], [report["faulty_transaction_id"]])
        self.assertNotIn(report["legitimate_transaction_id"], report["plan"]["selected_transaction_ids"])
        self.assertEqual(report["verification"]["integrity_status"], "VERIFIED")
        self.assertEqual(report["verification"]["checksum_verification"]["integrity_status"], "VERIFIED")
        self.assertEqual(report["verification"]["checksum_verification"]["unexpected_rows"], 0)
        self.assertTrue(report["verification"]["engine_checks_ok"])
        self.assertTrue(report["verification"]["foreign_keys_ok"])
        self.assertTrue(report["verification"]["original_statuses_restored"])
        self.assertTrue(report["verification"]["legitimate_order_preserved"])
        self.assertTrue(report["verification"]["state_matches_expected"])
        self.assertEqual(report["verification"]["failed_checks"], [])
        self.assertEqual(state["anchor_event_id"], report["anchor_event_id"])
        self.assertTrue(os.path.exists(report["report_path"]))
        with open(report["report_path"], "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["status"], "PASS")

    def test_inventory_crash_scenario_still_works(self):
        path = os.path.join(self.tmp.name, "inventory_crash.db")
        conn = db.connect(path)
        try:
            db.create_schema(conn)
            conn.execute("INSERT INTO customers(id, name, email) VALUES(1, 'Ada', 'ada@example.com')")
            original_stock = {}
            for sku, stock in (("APX-0001", 10), ("APX-0002", 20), ("APX-0003", 30)):
                conn.execute(
                    "INSERT INTO inventory(sku, name, stock, price_cents) VALUES(?, 'Item', ?, 100)",
                    (sku, stock))
                original_stock[sku] = stock
            anchor = change_tracker.latest_event_id(conn)

            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE inventory SET stock = 0")
            conn.execute("COMMIT")
            events = change_tracker.fetch_events(conn, after_event_id=anchor, order="id ASC")
            faulty_txn = next(event.transaction_id for event in events
                              if event.tbl == "inventory" and event.op == "U")

            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO customers(id, name, email) VALUES(2, 'Grace', 'g@example.com')")
            conn.execute(
                "INSERT INTO orders(id, customer_id, total_cents, status, idem_key, created_at) "
                "VALUES(9001, 2, 300, 'paid', 'inventory-legit', ?)", (db.clock.now(),))
            conn.execute(
                "INSERT INTO order_items(id, order_id, sku, qty, unit_cents) "
                "VALUES(9001, 9001, 'APX-0001', 3, 100)")
            conn.execute("COMMIT")
            events = change_tracker.fetch_events(conn, after_event_id=anchor, order="id ASC")
            legitimate_txn = events[-1].transaction_id

            plan = recovery_engine.create_plan(conn, tables=db.TABLES,
                                               anchor_event_id=anchor,
                                               transaction_ids=[faulty_txn])
            self.assertEqual(plan.selected_transaction_ids, (faulty_txn,))
            self.assertEqual({step.tbl for step in plan.steps}, {"inventory"})
            result = recovery_engine.execute_plan(conn, plan, tables=db.TABLES)

            stock = {row["sku"]: row["stock"] for row in conn.execute("SELECT sku, stock FROM inventory")}
            self.assertEqual(stock, original_stock)
            self.assertIsNotNone(conn.execute("SELECT 1 FROM orders WHERE id = 9001").fetchone())
            self.assertIsNotNone(conn.execute("SELECT 1 FROM order_items WHERE id = 9001").fetchone())
            self.assertNotIn(legitimate_txn, plan.selected_transaction_ids)
            self.assert_checks_ok(result["checks"])
            self.assert_checks_ok(integrity.verify_foreign_keys(conn, inspect_foreign_keys(conn, db.TABLES)))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()

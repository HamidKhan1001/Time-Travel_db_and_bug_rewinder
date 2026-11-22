import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timetravel import db
from timetravel.recovery import change_tracker, recovery_engine
from timetravel.recovery.integrity import RecoveryConflictError


class RecoveryOperationsTests(unittest.TestCase):
    def setUp(self):
        db.clock.offset = 0
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "recovery.db")
        self.conn = db.connect(self.path)
        db.create_schema(self.conn)

    def tearDown(self):
        db.clock.offset = 0
        self.conn.close()
        self.tmp.cleanup()

    def anchor(self):
        return change_tracker.latest_event_id(self.conn)

    def events_after(self, anchor):
        return change_tracker.fetch_events(self.conn, after_event_id=anchor, order="id ASC")

    def txn(self, statements):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            for sql, params in statements:
                self.conn.execute(sql, params)
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return [event.transaction_id for event in self.events_after(self.anchor() - 100000)]

    def add_inventory(self, sku, stock, name="Item", price=100):
        self.conn.execute(
            "INSERT INTO inventory(sku, name, stock, price_cents) VALUES(?, ?, ?, ?)",
            (sku, name, stock, price))

    def plan(self, anchor, transaction_ids=None):
        return recovery_engine.create_plan(self.conn, anchor_event_id=anchor,
                                           transaction_ids=transaction_ids)

    def audit(self, run_id):
        actions = self.conn.execute(
            "SELECT op, tbl, pk_json, status FROM recovery_actions WHERE run_id = ? ORDER BY id",
            (run_id,)).fetchall()
        run = self.conn.execute(
            "SELECT status, detail FROM recovery_runs WHERE id = ?", (run_id,)).fetchone()
        return run, [tuple(action) for action in actions]

    def test_update_recovery_restores_previous_values(self):
        self.add_inventory("APX-0001", 10, "Original", 2400)
        anchor = self.anchor()
        self.conn.execute("UPDATE inventory SET stock = 0, name = 'Broken' WHERE sku = 'APX-0001'")

        result = recovery_engine.execute_plan(self.conn, self.plan(anchor))
        row = self.conn.execute("SELECT * FROM inventory WHERE sku = 'APX-0001'").fetchone()
        self.assertEqual((row["stock"], row["name"], row["price_cents"]), (10, "Original", 2400))
        run, actions = self.audit(result["audit_run_id"])
        self.assertEqual(run["status"], "committed")
        self.assertEqual(actions, [("U", "inventory", '"APX-0001"', "applied")])

    def test_delete_recovery_restores_complete_row(self):
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(7, 'Ada', 'ada@example.com')")
        anchor = self.anchor()
        self.conn.execute("DELETE FROM customers WHERE id = 7")

        result = recovery_engine.execute_plan(self.conn, self.plan(anchor))
        row = self.conn.execute("SELECT * FROM customers WHERE id = 7").fetchone()
        self.assertEqual(dict(row), {"id": 7, "name": "Ada", "email": "ada@example.com"})
        run, actions = self.audit(result["audit_run_id"])
        self.assertEqual(run["status"], "committed")
        self.assertEqual(actions, [("I", "customers", "7", "applied")])

    def test_insert_recovery_removes_only_faulty_transaction(self):
        self.add_inventory("APX-0001", 5)
        anchor = self.anchor()
        self.conn.execute(
            "INSERT INTO inventory(sku, name, stock, price_cents) VALUES('APX-0009', 'Faulty', 1, 100)")
        faulty = self.events_after(anchor)[-1].transaction_id
        self.conn.execute(
            "INSERT INTO inventory(sku, name, stock, price_cents) VALUES('APX-0010', 'Legit', 2, 100)")

        recovery_engine.execute_plan(self.conn, self.plan(anchor, [faulty]))
        self.assertIsNone(self.conn.execute("SELECT 1 FROM inventory WHERE sku = 'APX-0009'").fetchone())
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM inventory WHERE sku = 'APX-0010'").fetchone())

    def test_multiple_operations_in_one_transaction(self):
        self.add_inventory("APX-0001", 5)
        self.add_inventory("APX-0002", 7)
        anchor = self.anchor()
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute("UPDATE inventory SET stock = 0 WHERE sku = 'APX-0001'")
        self.conn.execute("DELETE FROM inventory WHERE sku = 'APX-0002'")
        self.conn.execute(
            "INSERT INTO inventory(sku, name, stock, price_cents) VALUES('APX-0003', 'New', 3, 100)")
        self.conn.execute("COMMIT")

        plan = self.plan(anchor)
        self.assertEqual(len(plan.steps), 3)
        self.assertEqual(len(plan.transaction_ids), 1)
        result = recovery_engine.execute_plan(self.conn, plan)
        stocks = {row["sku"]: row["stock"] for row in self.conn.execute("SELECT sku, stock FROM inventory")}
        self.assertEqual(stocks, {"APX-0001": 5, "APX-0002": 7})
        run, actions = self.audit(result["audit_run_id"])
        self.assertEqual(run["status"], "committed")
        self.assertEqual(len(actions), 3)

    def test_multiple_transactions(self):
        self.add_inventory("APX-0001", 5)
        self.add_inventory("APX-0002", 7)
        anchor = self.anchor()
        self.conn.execute("UPDATE inventory SET stock = 0 WHERE sku = 'APX-0001'")
        self.conn.execute("DELETE FROM inventory WHERE sku = 'APX-0002'")
        self.conn.execute(
            "INSERT INTO inventory(sku, name, stock, price_cents) VALUES('APX-0003', 'New', 3, 100)")

        plan = self.plan(anchor)
        self.assertEqual(len(plan.transaction_ids), 3)
        recovery_engine.execute_plan(self.conn, plan)
        stocks = {row["sku"]: row["stock"] for row in self.conn.execute("SELECT sku, stock FROM inventory")}
        self.assertEqual(stocks, {"APX-0001": 5, "APX-0002": 7})

    def test_duplicate_primary_key_conflict(self):
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(1, 'Original', 'a@example.com')")
        anchor = self.anchor()
        self.conn.execute("DELETE FROM customers WHERE id = 1")
        faulty = self.events_after(anchor)[-1].transaction_id
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(1, 'Legit', 'b@example.com')")

        with self.assertRaises(RecoveryConflictError) as raised:
            recovery_engine.execute_plan(self.conn, self.plan(anchor, [faulty]))
        self.assertIn("duplicate-primary-key", [conflict["kind"] for conflict in raised.exception.conflicts])
        rows = self.conn.execute("SELECT name FROM customers WHERE id = 1").fetchall()
        self.assertEqual([row["name"] for row in rows], ["Legit"])

    def test_missing_record_conflict(self):
        self.add_inventory("APX-0001", 10)
        anchor = self.anchor()
        self.conn.execute("UPDATE inventory SET stock = 0 WHERE sku = 'APX-0001'")
        faulty = self.events_after(anchor)[-1].transaction_id
        self.conn.execute("DELETE FROM inventory WHERE sku = 'APX-0001'")

        with self.assertRaises(RecoveryConflictError) as raised:
            recovery_engine.execute_plan(self.conn, self.plan(anchor, [faulty]))
        self.assertIn("missing-record", [conflict["kind"] for conflict in raised.exception.conflicts])
        self.assertIsNone(self.conn.execute("SELECT 1 FROM inventory WHERE sku = 'APX-0001'").fetchone())

    def test_conflicting_change_is_detected_before_recovery(self):
        self.add_inventory("APX-0001", 10)
        anchor = self.anchor()
        self.conn.execute("UPDATE inventory SET stock = 0 WHERE sku = 'APX-0001'")
        faulty = self.events_after(anchor)[-1].transaction_id
        self.conn.execute("UPDATE inventory SET stock = 7 WHERE sku = 'APX-0001'")

        with self.assertRaises(RecoveryConflictError) as raised:
            recovery_engine.execute_plan(self.conn, self.plan(anchor, [faulty]))
        self.assertIn("conflicting-change", [conflict["kind"] for conflict in raised.exception.conflicts])
        self.assertEqual(self.conn.execute("SELECT stock FROM inventory WHERE sku = 'APX-0001'").fetchone()[0], 7)

    def test_delete_recovery_rejects_unique_constraint_conflict(self):
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(1, 'Ada', 'ada@example.com')")
        self.conn.execute(
            "INSERT INTO orders(id, customer_id, total_cents, status, idem_key, created_at) "
            "VALUES(1001, 1, 100, 'paid', 'key-1', ?)", (db.clock.now(),))
        anchor = self.anchor()
        self.conn.execute("DELETE FROM orders WHERE id = 1001")
        faulty = self.events_after(anchor)[-1].transaction_id
        self.conn.execute(
            "INSERT INTO orders(id, customer_id, total_cents, status, idem_key, created_at) "
            "VALUES(1002, 1, 200, 'paid', 'key-1', ?)", (db.clock.now(),))

        with self.assertRaises(RecoveryConflictError) as raised:
            recovery_engine.execute_plan(self.conn, self.plan(anchor, [faulty]))
        self.assertIn("unique-constraint", [conflict["kind"] for conflict in raised.exception.conflicts])
        self.assertIsNone(self.conn.execute("SELECT 1 FROM orders WHERE id = 1001").fetchone())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM orders WHERE idem_key = 'key-1'").fetchone()[0], 1)

    def test_recovery_failure_rolls_back_all_changes(self):
        self.add_inventory("APX-0001", 5)
        self.add_inventory("APX-0002", 7)
        anchor = self.anchor()
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute("UPDATE inventory SET stock = 0 WHERE sku = 'APX-0001'")
        self.conn.execute("UPDATE inventory SET stock = 0 WHERE sku = 'APX-0002'")
        self.conn.execute("COMMIT")
        plan = self.plan(anchor)

        original = recovery_engine._apply_step
        live = self.conn

        def failing_apply(conn, step, tables):
            if conn is live and step.pk == "APX-0002":
                raise RuntimeError("injected recovery failure")
            return original(conn, step, tables)

        recovery_engine._apply_step = failing_apply
        try:
            with self.assertRaises(RuntimeError):
                recovery_engine.execute_plan(self.conn, plan)
        finally:
            recovery_engine._apply_step = original

        stocks = {row["sku"]: row["stock"] for row in self.conn.execute("SELECT sku, stock FROM inventory")}
        self.assertEqual(stocks, {"APX-0001": 0, "APX-0002": 0})
        run_id = self.conn.execute("SELECT MAX(id) FROM recovery_runs").fetchone()[0]
        run, actions = self.audit(run_id)
        self.assertEqual(run["status"], "rolled-back")
        self.assertEqual([action[3] for action in actions], ["failed", "failed"])


if __name__ == "__main__":
    unittest.main()

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timetravel import db
from timetravel.recovery import (
    UnsupportedRelationshipError,
    change_tracker,
    explain_plan,
    inspect_foreign_keys,
    recovery_engine,
    transaction_logger,
)
from timetravel.recovery.integrity import RecoveryConflictError, verify_foreign_keys


CASCADE_SCHEMA = """
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL);
CREATE TABLE inventory (
  sku TEXT PRIMARY KEY, name TEXT NOT NULL,
  stock INTEGER NOT NULL CHECK (stock >= 0), price_cents INTEGER NOT NULL);
CREATE TABLE orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  total_cents INTEGER NOT NULL, status TEXT NOT NULL,
  idem_key TEXT UNIQUE, created_at REAL NOT NULL);
CREATE TABLE order_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  sku TEXT NOT NULL REFERENCES inventory(sku),
  qty INTEGER NOT NULL, unit_cents INTEGER NOT NULL);
"""


class ForeignKeyRecoveryTests(unittest.TestCase):
    def setUp(self):
        db.clock.offset = 0
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "fk.db")
        self.conn = db.connect(self.path)
        db.create_schema(self.conn)

    def tearDown(self):
        db.clock.offset = 0
        self.conn.close()
        self.tmp.cleanup()

    def use_cascade_schema(self):
        self.conn.close()
        self.path = os.path.join(self.tmp.name, "fk_cascade.db")
        raw = sqlite3.connect(self.path)
        raw.executescript(CASCADE_SCHEMA)
        raw.close()
        self.conn = db.connect(self.path)
        transaction_logger.ensure_schema(self.conn, db.TABLES, db.clock.now)

    def anchor(self):
        return change_tracker.latest_event_id(self.conn)

    def events_after(self, anchor):
        return change_tracker.fetch_events(self.conn, after_event_id=anchor, order="id ASC")

    def faulty_transaction(self, anchor):
        return self.events_after(anchor)[-1].transaction_id

    def seed_inventory(self, sku="APX-0001"):
        self.conn.execute(
            "INSERT INTO inventory(sku, name, stock, price_cents) VALUES(?, 'Original', 10, 2400)", (sku,))

    def seed_tree(self):
        self.seed_inventory()
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(1, 'Ada', 'ada@example.com')")
        self.conn.execute(
            "INSERT INTO orders(id, customer_id, total_cents, status, idem_key, created_at) "
            "VALUES(1001, 1, 2400, 'paid', 'tree-1', ?)", (db.clock.now(),))
        self.conn.execute(
            "INSERT INTO order_items(id, order_id, sku, qty, unit_cents) VALUES(1, 1001, 'APX-0001', 2, 1200)")

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

    def assert_fk_valid(self):
        failed = [check for check in verify_foreign_keys(self.conn, inspect_foreign_keys(self.conn, db.TABLES))
                  if not check["ok"]]
        self.assertEqual(failed, [])

    def test_parent_and_child_deletes_restore_in_dependency_order(self):
        self.seed_tree()
        anchor = self.anchor()
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute("DELETE FROM order_items WHERE id = 1")
        self.conn.execute("DELETE FROM orders WHERE id = 1001")
        self.conn.execute("DELETE FROM customers WHERE id = 1")
        self.conn.execute("COMMIT")

        plan = self.plan(anchor)
        self.assertEqual(tuple(step.tbl for step in plan.execution_steps),
                         ("customers", "orders", "order_items"))
        self.assertTrue(all(edge.reason == "restore-parent-before-child" for edge in plan.dependency_edges))
        summary = explain_plan(plan)
        self.assertEqual(len(summary["relationships"]["relationships"]), 3)
        result = recovery_engine.execute_plan(self.conn, plan)

        self.assertEqual(self.conn.execute("SELECT name FROM customers WHERE id = 1").fetchone()[0], "Ada")
        self.assertEqual(self.conn.execute("SELECT status FROM orders WHERE id = 1001").fetchone()[0], "paid")
        self.assertEqual(self.conn.execute("SELECT qty FROM order_items WHERE id = 1").fetchone()[0], 2)
        run, actions = self.audit(result["audit_run_id"])
        self.assertEqual(run["status"], "committed")
        self.assertEqual([action[1] for action in actions], ["customers", "orders", "order_items"])
        self.assert_fk_valid()
        self.assertEqual([check for check in result["checks"] if not check["ok"]], [])

    def test_child_delete_restores_without_touching_parent(self):
        self.seed_tree()
        anchor = self.anchor()
        self.conn.execute("DELETE FROM order_items WHERE id = 1")

        result = recovery_engine.execute_plan(self.conn, self.plan(anchor))
        self.assertEqual(self.conn.execute("SELECT qty FROM order_items WHERE id = 1").fetchone()[0], 2)
        self.assertEqual(self.conn.execute("SELECT name FROM customers WHERE id = 1").fetchone()[0], "Ada")
        self.assertEqual(result["steps_applied"], 1)
        self.assert_fk_valid()

    def test_multiple_related_updates_restore_all_values(self):
        self.seed_tree()
        anchor = self.anchor()
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute("UPDATE customers SET name = 'Broken' WHERE id = 1")
        self.conn.execute("UPDATE orders SET status = 'broken' WHERE id = 1001")
        self.conn.execute("UPDATE order_items SET qty = 99, unit_cents = 1 WHERE id = 1")
        self.conn.execute("COMMIT")

        recovery_engine.execute_plan(self.conn, self.plan(anchor))
        self.assertEqual(self.conn.execute("SELECT name FROM customers WHERE id = 1").fetchone()[0], "Ada")
        self.assertEqual(self.conn.execute("SELECT status FROM orders WHERE id = 1001").fetchone()[0], "paid")
        item = self.conn.execute("SELECT qty, unit_cents FROM order_items WHERE id = 1").fetchone()
        self.assertEqual((item["qty"], item["unit_cents"]), (2, 1200))
        self.assert_fk_valid()

    def test_cascade_delete_restores_parent_before_children(self):
        self.use_cascade_schema()
        self.seed_tree()
        anchor = self.anchor()
        self.conn.execute("DELETE FROM customers WHERE id = 1")
        for table, pk in (("customers", 1), ("orders", 1001), ("order_items", 1)):
            self.assertIsNone(self.conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (pk,)).fetchone())

        plan = self.plan(anchor)
        self.assertEqual(len(plan.steps), 3)
        self.assertEqual(tuple(step.tbl for step in plan.execution_steps),
                         ("customers", "orders", "order_items"))
        result = recovery_engine.execute_plan(self.conn, plan)
        run, actions = self.audit(result["audit_run_id"])
        self.assertEqual(run["status"], "committed")
        self.assertEqual([action[1] for action in actions], ["customers", "orders", "order_items"])
        self.assertEqual(self.conn.execute("SELECT qty FROM order_items WHERE id = 1").fetchone()[0], 2)
        self.assert_fk_valid()

    def test_reverse_insert_deletes_children_before_parent(self):
        self.seed_inventory()
        anchor = self.anchor()
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(2, 'Faulty', 'f@example.com')")
        self.conn.execute(
            "INSERT INTO orders(id, customer_id, total_cents, status, idem_key, created_at) "
            "VALUES(1002, 2, 100, 'paid', 'faulty-2', ?)", (db.clock.now(),))
        self.conn.execute(
            "INSERT INTO order_items(id, order_id, sku, qty, unit_cents) VALUES(2, 1002, 'APX-0001', 1, 100)")
        self.conn.execute("COMMIT")

        plan = self.plan(anchor)
        self.assertEqual(tuple(step.tbl for step in plan.execution_steps),
                         ("order_items", "orders", "customers"))
        self.assertTrue(all(edge.reason == "remove-child-before-parent" for edge in plan.dependency_edges))
        result = recovery_engine.execute_plan(self.conn, plan)
        run, actions = self.audit(result["audit_run_id"])
        self.assertEqual(run["status"], "committed")
        self.assertEqual([action[1] for action in actions], ["order_items", "orders", "customers"])
        for table, pk in (("customers", 2), ("orders", 1002), ("order_items", 2)):
            self.assertIsNone(self.conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (pk,)).fetchone())
        self.assert_fk_valid()

    def test_duplicate_parent_record_blocks_recovery(self):
        self.seed_tree()
        anchor = self.anchor()
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute("DELETE FROM order_items WHERE id = 1")
        self.conn.execute("DELETE FROM orders WHERE id = 1001")
        self.conn.execute("DELETE FROM customers WHERE id = 1")
        self.conn.execute("COMMIT")
        faulty = self.faulty_transaction(anchor)
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(1, 'Legit', 'legit@example.com')")

        with self.assertRaises(RecoveryConflictError) as raised:
            recovery_engine.execute_plan(self.conn, self.plan(anchor, [faulty]))
        kinds = [conflict["kind"] for conflict in raised.exception.conflicts]
        self.assertIn("duplicate-primary-key", kinds)
        self.assertEqual(self.conn.execute("SELECT name FROM customers WHERE id = 1").fetchone()[0], "Legit")
        self.assert_fk_valid()

    def test_missing_parent_reference_blocks_child_restore(self):
        self.seed_inventory()
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(1, 'Ada', 'ada@example.com')")
        self.conn.execute(
            "INSERT INTO orders(id, customer_id, total_cents, status, idem_key, created_at) "
            "VALUES(1001, 1, 100, 'paid', 'missing-1', ?)", (db.clock.now(),))
        anchor = self.anchor()
        self.conn.execute("DELETE FROM orders WHERE id = 1001")
        faulty = self.faulty_transaction(anchor)
        self.conn.execute("DELETE FROM customers WHERE id = 1")

        with self.assertRaises(RecoveryConflictError) as raised:
            recovery_engine.execute_plan(self.conn, self.plan(anchor, [faulty]))
        self.assertIn("missing-parent-reference", [conflict["kind"] for conflict in raised.exception.conflicts])
        self.assertIsNone(self.conn.execute("SELECT 1 FROM orders WHERE id = 1001").fetchone())
        self.assert_fk_valid()

    def test_dependent_child_rows_block_parent_deletion(self):
        self.seed_inventory()
        anchor = self.anchor()
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(1, 'Faulty', 'f@example.com')")
        faulty = self.faulty_transaction(anchor)
        self.conn.execute(
            "INSERT INTO orders(id, customer_id, total_cents, status, idem_key, created_at) "
            "VALUES(1001, 1, 100, 'paid', 'legit-1', ?)", (db.clock.now(),))

        with self.assertRaises(RecoveryConflictError) as raised:
            recovery_engine.execute_plan(self.conn, self.plan(anchor, [faulty]))
        self.assertIn("dependent-rows-exist", [conflict["kind"] for conflict in raised.exception.conflicts])
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM customers WHERE id = 1").fetchone())
        self.assert_fk_valid()

    def test_cascade_child_loss_is_detected(self):
        self.use_cascade_schema()
        self.seed_inventory()
        anchor = self.anchor()
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(1, 'Faulty', 'f@example.com')")
        faulty = self.faulty_transaction(anchor)
        self.conn.execute(
            "INSERT INTO orders(id, customer_id, total_cents, status, idem_key, created_at) "
            "VALUES(1001, 1, 100, 'paid', 'legit-1', ?)", (db.clock.now(),))

        with self.assertRaises(RecoveryConflictError) as raised:
            recovery_engine.execute_plan(self.conn, self.plan(anchor, [faulty]))
        self.assertIn("cascade-child-loss", [conflict["kind"] for conflict in raised.exception.conflicts])
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM orders WHERE id = 1001").fetchone())
        self.assert_fk_valid()

    def test_unsupported_relationships_are_rejected(self):
        path = os.path.join(self.tmp.name, "unsupported.db")
        raw = sqlite3.connect(path)
        raw.row_factory = sqlite3.Row
        raw.executescript("""
        CREATE TABLE profiles(id INTEGER PRIMARY KEY, code TEXT UNIQUE);
        CREATE TABLE accounts(id INTEGER PRIMARY KEY, profile_code TEXT REFERENCES profiles(code));
        CREATE TABLE pairs(a TEXT, b TEXT, PRIMARY KEY(a, b));
        CREATE TABLE children(id INTEGER PRIMARY KEY, a TEXT, b TEXT, FOREIGN KEY(a, b) REFERENCES pairs(a, b));
        """)
        try:
            with self.assertRaises(UnsupportedRelationshipError):
                inspect_foreign_keys(raw, {"profiles": "id", "accounts": "id"})
            with self.assertRaises(UnsupportedRelationshipError):
                inspect_foreign_keys(raw, {"pairs": "a", "children": "id"})
        finally:
            raw.close()

    def test_partial_recovery_failure_rolls_back_all_related_changes(self):
        self.seed_tree()
        anchor = self.anchor()
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute("UPDATE customers SET name = 'Broken' WHERE id = 1")
        self.conn.execute("UPDATE orders SET status = 'broken' WHERE id = 1001")
        self.conn.execute("UPDATE order_items SET qty = 99 WHERE id = 1")
        self.conn.execute("COMMIT")
        plan = self.plan(anchor)

        original = recovery_engine._apply_step
        live = self.conn

        def failing_apply(conn, step, tables):
            if conn is live and step.tbl == "order_items":
                raise RuntimeError("injected dependency failure")
            return original(conn, step, tables)

        recovery_engine._apply_step = failing_apply
        try:
            with self.assertRaises(RuntimeError):
                recovery_engine.execute_plan(self.conn, plan)
        finally:
            recovery_engine._apply_step = original

        self.assertEqual(self.conn.execute("SELECT name FROM customers WHERE id = 1").fetchone()[0], "Broken")
        self.assertEqual(self.conn.execute("SELECT status FROM orders WHERE id = 1001").fetchone()[0], "broken")
        self.assertEqual(self.conn.execute("SELECT qty FROM order_items WHERE id = 1").fetchone()[0], 99)
        run_id = self.conn.execute("SELECT MAX(id) FROM recovery_runs").fetchone()[0]
        run, _ = self.audit(run_id)
        self.assertEqual(run["status"], "rolled-back")
        self.assert_fk_valid()


if __name__ == "__main__":
    unittest.main()

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timetravel import db, guard
from timetravel.recovery import (
    UnsupportedRelationshipError,
    change_tracker,
    recovery_engine,
    recovery_planner,
    verification,
)
from timetravel.recovery.integrity import RecoveryConflictError


class Phase9ComprehensiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_root = tempfile.TemporaryDirectory()
        db.clock.offset = 0

    @classmethod
    def tearDownClass(cls):
        db.clock.offset = 0
        cls.tmp_root.cleanup()

    def setUp(self):
        db.clock.offset = 0
        self.tmp = tempfile.TemporaryDirectory(dir=self.tmp_root.name)
        self.path = os.path.join(self.tmp.name, "phase9.db")
        self.conn = db.connect(self.path)
        db.create_schema(self.conn)

    def tearDown(self):
        try:
            if self.conn:
                self.conn.close()
        finally:
            self.tmp.cleanup()
            db.clock.offset = 0

    def anchor(self):
        return change_tracker.latest_event_id(self.conn)

    def events_after(self, anchor):
        return change_tracker.fetch_events(self.conn, after_event_id=anchor, order="id ASC")

    def add_inventory(self, sku, stock, name="Item", price=100):
        self.conn.execute(
            "INSERT INTO inventory(sku, name, stock, price_cents) VALUES(?, ?, ?, ?)",
            (sku, name, stock, price))

    def seed_customer_order_item(self):
        self.add_inventory("SKU-1", 10, "Box", 100)
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(1, 'Ada', 'ada@example.com')")
        self.conn.execute(
            "INSERT INTO orders(id, customer_id, total_cents, status, idem_key, created_at) "
            "VALUES(1001, 1, 100, 'paid', 'k1', ?)", (db.clock.now(),))
        self.conn.execute(
            "INSERT INTO order_items(id, order_id, sku, qty, unit_cents) VALUES(1, 1001, 'SKU-1', 1, 100)")

    def plan(self, anchor, **kwargs):
        return recovery_engine.create_plan(self.conn, anchor_event_id=anchor, **kwargs)

    def test_01_update_recovery(self):
        self.add_inventory("SKU-1", 10, "Old", 100)
        anchor = self.anchor()
        self.conn.execute("UPDATE inventory SET stock = 0, name = 'Broken' WHERE sku = 'SKU-1'")
        recovery_engine.execute_plan(self.conn, self.plan(anchor))
        row = self.conn.execute("SELECT stock, name FROM inventory WHERE sku='SKU-1'").fetchone()
        self.assertEqual(tuple(row), (10, "Old"))

    def test_02_delete_recovery(self):
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(7, 'Ada', 'ada@example.com')")
        anchor = self.anchor()
        self.conn.execute("DELETE FROM customers WHERE id = 7")
        recovery_engine.execute_plan(self.conn, self.plan(anchor))
        row = self.conn.execute("SELECT name, email FROM customers WHERE id=7").fetchone()
        self.assertEqual(tuple(row), ("Ada", "ada@example.com"))

    def test_03_insert_recovery(self):
        self.add_inventory("SKU-1", 5)
        anchor = self.anchor()
        self.conn.execute(
            "INSERT INTO inventory(sku, name, stock, price_cents) VALUES('SKU-BAD', 'Bad', 1, 100)")
        faulty = self.events_after(anchor)[-1].transaction_id
        self.conn.execute(
            "INSERT INTO inventory(sku, name, stock, price_cents) VALUES('SKU-GOOD', 'Good', 2, 100)")
        recovery_engine.execute_plan(self.conn, self.plan(anchor, transaction_ids=[faulty]))
        self.assertIsNone(self.conn.execute("SELECT 1 FROM inventory WHERE sku='SKU-BAD'").fetchone())
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM inventory WHERE sku='SKU-GOOD'").fetchone())

    def test_04_foreign_key_recovery(self):
        self.seed_customer_order_item()
        anchor = self.anchor()
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute("DELETE FROM order_items WHERE id = 1")
        self.conn.execute("DELETE FROM orders WHERE id = 1001")
        self.conn.execute("DELETE FROM customers WHERE id = 1")
        self.conn.execute("COMMIT")
        plan = self.plan(anchor)
        self.assertEqual(tuple(step.tbl for step in plan.execution_steps),
                         ("customers", "orders", "order_items"))
        result = recovery_engine.execute_plan(self.conn, plan)
        self.assertTrue(all(c["ok"] for c in result["checks"]))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM orders WHERE id=1001").fetchone()[0], 1)

    def test_05_multiple_table_recovery(self):
        self.seed_customer_order_item()
        anchor = self.anchor()
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute("UPDATE customers SET name='Broken' WHERE id=1")
        self.conn.execute("UPDATE orders SET status='broken' WHERE id=1001")
        self.conn.execute("UPDATE inventory SET stock=0 WHERE sku='SKU-1'")
        self.conn.execute("UPDATE order_items SET qty=99 WHERE id=1")
        self.conn.execute("COMMIT")
        recovery_engine.execute_plan(self.conn, self.plan(anchor))
        self.assertEqual(self.conn.execute("SELECT name FROM customers WHERE id=1").fetchone()[0], "Ada")
        self.assertEqual(self.conn.execute("SELECT status FROM orders WHERE id=1001").fetchone()[0], "paid")
        self.assertEqual(self.conn.execute("SELECT stock FROM inventory WHERE sku='SKU-1'").fetchone()[0], 10)
        self.assertEqual(self.conn.execute("SELECT qty FROM order_items WHERE id=1").fetchone()[0], 1)

    def test_06_multiple_transaction_recovery(self):
        self.add_inventory("SKU-1", 5)
        self.add_inventory("SKU-2", 7)
        anchor = self.anchor()
        self.conn.execute("UPDATE inventory SET stock=0 WHERE sku='SKU-1'")
        self.conn.execute("DELETE FROM inventory WHERE sku='SKU-2'")
        self.conn.execute("INSERT INTO inventory(sku,name,stock,price_cents) VALUES('SKU-3','N',3,1)")
        plan = self.plan(anchor)
        self.assertGreaterEqual(len(plan.transaction_ids), 3)
        recovery_engine.execute_plan(self.conn, plan)
        stocks = {r["sku"]: r["stock"] for r in self.conn.execute("SELECT sku, stock FROM inventory")}
        self.assertEqual(stocks, {"SKU-1": 5, "SKU-2": 7})

    def test_07_second_crash_scenario(self):
        from tests.setup_second_crash import setup_scenario
        from tests.run_second_crash import run_scenario
        setup_scenario(self.tmp.name)
        report = run_scenario(directory=self.tmp.name)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["verification"]["integrity_status"], "VERIFIED")

    def test_08_checksum_verification(self):
        baseline = verification.capture_reference(self.conn)
        self.addCleanup(baseline.close)
        report = verification.verify_state_against(self.conn, baseline)
        self.assertEqual(report["integrity_status"], "VERIFIED")
        self.assertEqual(report["mismatching_rows"], 0)
        self.assertEqual(report["missing_rows"], 0)
        self.assertEqual(report["unexpected_rows"], 0)

    def test_09_checksum_mismatch_handling(self):
        self.add_inventory("SKU-1", 5)
        anchor = self.anchor()
        self.conn.execute("INSERT INTO inventory(sku,name,stock,price_cents) VALUES('SKU-2','Bad',1,1)")
        baseline = verification.capture_reference(self.conn)
        self.addCleanup(baseline.close)
        plan = self.plan(anchor)
        with self.assertRaises(RuntimeError):
            recovery_engine.execute_plan(self.conn, plan, reference=baseline)
        self.assertIsNotNone(self.conn.execute("SELECT 1 FROM inventory WHERE sku='SKU-2'").fetchone())
        run = self.conn.execute("SELECT status FROM recovery_runs ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(run["status"], "rolled-back")

    def test_10_partial_recovery_failure(self):
        self.add_inventory("SKU-1", 5)
        self.add_inventory("SKU-2", 7)
        anchor = self.anchor()
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute("UPDATE inventory SET stock=0 WHERE sku='SKU-1'")
        self.conn.execute("UPDATE inventory SET stock=0 WHERE sku='SKU-2'")
        self.conn.execute("COMMIT")
        plan = self.plan(anchor)
        original = recovery_engine._apply_step
        live = self.conn

        def failing(conn, step, tables):
            if conn is live and step.pk == "SKU-2":
                raise RuntimeError("injected")
            return original(conn, step, tables)

        recovery_engine._apply_step = failing
        try:
            with self.assertRaises(RuntimeError):
                recovery_engine.execute_plan(self.conn, plan)
        finally:
            recovery_engine._apply_step = original
        stocks = {r["sku"]: r["stock"] for r in self.conn.execute("SELECT sku, stock FROM inventory")}
        self.assertEqual(stocks, {"SKU-1": 0, "SKU-2": 0})

    def test_11_transaction_rollback(self):
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute("INSERT INTO customers(id,name,email) VALUES(1,'A','a@example.com')")
        self.conn.execute("INSERT INTO customers(id,name,email) VALUES(2,'B','b@example.com')")
        self.conn.execute("ROLLBACK")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0], 0)
        self.assertEqual(change_tracker.latest_event_id(self.conn), 0)

    def test_12_duplicate_primary_keys(self):
        self.conn.execute("INSERT INTO customers(id,name,email) VALUES(1,'Orig','o@example.com')")
        anchor = self.anchor()
        self.conn.execute("DELETE FROM customers WHERE id=1")
        faulty = self.events_after(anchor)[-1].transaction_id
        self.conn.execute("INSERT INTO customers(id,name,email) VALUES(1,'Legit','l@example.com')")
        with self.assertRaises(RecoveryConflictError) as ctx:
            recovery_engine.execute_plan(self.conn, self.plan(anchor, transaction_ids=[faulty]))
        self.assertIn("duplicate-primary-key", [c["kind"] for c in ctx.exception.conflicts])

    def test_13_missing_records(self):
        self.add_inventory("SKU-1", 10)
        anchor = self.anchor()
        self.conn.execute("UPDATE inventory SET stock=0 WHERE sku='SKU-1'")
        faulty = self.events_after(anchor)[-1].transaction_id
        self.conn.execute("DELETE FROM inventory WHERE sku='SKU-1'")
        with self.assertRaises(RecoveryConflictError) as ctx:
            recovery_engine.execute_plan(self.conn, self.plan(anchor, transaction_ids=[faulty]))
        self.assertIn("missing-record", [c["kind"] for c in ctx.exception.conflicts])

    def test_14_concurrent_modification_conflicts(self):
        self.add_inventory("SKU-1", 10)
        anchor = self.anchor()
        self.conn.execute("UPDATE inventory SET stock=0 WHERE sku='SKU-1'")
        faulty = self.events_after(anchor)[-1].transaction_id
        # concurrent modification after faulty transaction
        self.conn.execute("UPDATE inventory SET stock=7 WHERE sku='SKU-1'")
        with self.assertRaises(RecoveryConflictError) as ctx:
            recovery_engine.execute_plan(self.conn, self.plan(anchor, transaction_ids=[faulty]))
        self.assertIn("conflicting-change", [c["kind"] for c in ctx.exception.conflicts])
        self.assertEqual(self.conn.execute("SELECT stock FROM inventory WHERE sku='SKU-1'").fetchone()[0], 7)

    def test_15_large_dataset_performance(self):
        for i in range(1000):
            self.conn.execute(
                "INSERT INTO inventory(sku,name,stock,price_cents) VALUES(?,?,?,?)",
                (f"SKU-{i}", f"Item {i}", i % 100 + 1, 100))
        anchor = self.anchor()
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute("UPDATE inventory SET stock = 0")
        self.conn.execute("COMMIT")
        plan = self.plan(anchor)
        self.assertEqual(len(plan.steps), 1000)
        result = recovery_engine.execute_plan(self.conn, plan)
        self.assertEqual(result["verification"]["integrity_status"], "VERIFIED")
        bad = self.conn.execute("SELECT COUNT(*) FROM inventory WHERE stock=0").fetchone()[0]
        self.assertEqual(bad, 0)

    def test_16_sql_firewall_blocks_unsafe_statements(self):
        blocked = guard.analyze("UPDATE inventory SET stock = 0")
        self.assertFalse(blocked["allowed"])
        self.assertEqual(blocked["rule"], "unscoped-write")
        blocked2 = guard.analyze("DROP TABLE inventory")
        self.assertFalse(blocked2["allowed"])
        approved = guard.analyze("DELETE FROM inventory", approved=True)
        self.assertTrue(approved["allowed"])

    def test_17_unsafe_recovery_plan_rejected(self):
        import dataclasses
        self.add_inventory("SKU-1", 1)
        anchor = self.anchor()
        self.conn.execute("DELETE FROM inventory WHERE sku='SKU-1'")
        plan = self.plan(anchor)
        # Tamper with plan to make it unsafe: replace step with bad table
        bad_step = dataclasses.replace(plan.steps[0], tbl="nonexistent")
        bad_plan = dataclasses.replace(plan, steps=(bad_step,))
        with self.assertRaises((ValueError, RecoveryConflictError, RuntimeError, KeyError, UnsupportedRelationshipError)):
            recovery_engine.execute_plan(self.conn, bad_plan)

    def test_18_unsupported_operations_fail_safely(self):
        import dataclasses
        self.add_inventory("SKU-1", 1)
        anchor = self.anchor()
        self.conn.execute("UPDATE inventory SET stock=2 WHERE sku='SKU-1'")
        plan = self.plan(anchor)
        bad_step = dataclasses.replace(plan.steps[0], op="X", source_op="X")
        bad_plan = dataclasses.replace(plan, steps=(bad_step,))
        with self.assertRaises((ValueError, RuntimeError, RecoveryConflictError)):
            recovery_engine.execute_plan(self.conn, bad_plan)
        # DB unchanged by failed unsupported operation
        self.assertEqual(self.conn.execute("SELECT stock FROM inventory WHERE sku='SKU-1'").fetchone()[0], 2)

    def test_19_failed_integrity_verification_prevents_success(self):
        self.add_inventory("SKU-1", 5)
        anchor = self.anchor()
        self.conn.execute("INSERT INTO inventory(sku,name,stock,price_cents) VALUES('SKU-TEMP','T',1,1)")
        baseline = verification.capture_reference(self.conn)
        self.addCleanup(baseline.close)
        plan = self.plan(anchor)
        with self.assertRaises(RuntimeError) as ctx:
            recovery_engine.execute_plan(self.conn, plan, reference=baseline)
        self.assertIn("checks failed", str(ctx.exception).lower() + "checksum")
        # ensure not marked committed as success path
        run = self.conn.execute("SELECT status FROM recovery_runs ORDER BY id DESC LIMIT 1").fetchone()
        self.assertNotEqual(run["status"], "committed")


if __name__ == "__main__":
    unittest.main()

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timetravel import db
from timetravel.recovery import change_tracker, integrity, recovery_engine, verification


class IntegrityVerificationTests(unittest.TestCase):
    def setUp(self):
        db.clock.offset = 0
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "verification.db")
        self.conn = db.connect(self.path)
        db.create_schema(self.conn)
        self.seed()

    def tearDown(self):
        db.clock.offset = 0
        self.conn.close()
        self.tmp.cleanup()

    def seed(self):
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(1, 'Ada', 'ada@example.com')")
        self.conn.execute(
            "INSERT INTO inventory(sku, name, stock, price_cents) VALUES('SKU-1', 'Box', 4, 100)")

    def baseline(self):
        baseline = verification.capture_reference(self.conn)
        self.addCleanup(baseline.close)
        return baseline

    def test_checksum_helpers_are_consistent(self):
        self.assertEqual(integrity.checksum(self.conn, db.TABLES),
                         verification.checksum_database(self.conn, db.TABLES))

    def test_same_state_verifies_all_rows(self):
        report = verification.verify_state_against(self.conn, self.baseline())
        self.assertEqual(report["integrity_status"], "VERIFIED")
        self.assertTrue(report["checksum_match"])
        self.assertEqual(report["original_checksum"], report["recovered_checksum"])
        self.assertEqual(report["total_rows_checked"], 2)
        self.assertEqual(report["matching_rows"], 2)
        self.assertEqual(report["mismatching_rows"], 0)
        self.assertEqual(report["missing_rows"], 0)
        self.assertEqual(report["unexpected_rows"], 0)
        self.assertEqual(report["primary_key_mismatches"], 0)

    def test_modified_row_is_detected(self):
        baseline = self.baseline()
        self.conn.execute("UPDATE customers SET name = 'Changed' WHERE id = 1")
        report = verification.verify_state_against(self.conn, baseline)
        self.assertEqual(report["integrity_status"], "FAILED")
        self.assertFalse(report["checksum_match"])
        self.assertEqual(report["mismatching_rows"], 1)
        self.assertEqual(report["missing_rows"], 0)
        self.assertEqual(report["unexpected_rows"], 0)
        self.assertEqual(report["samples"]["modified"], [["customers", "1"]])

    def test_missing_unexpected_and_primary_key_mismatch_are_detected(self):
        baseline = self.baseline()
        self.conn.execute("DELETE FROM customers WHERE id = 1")
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(99, 'Ada', 'ada@example.com')")
        report = verification.verify_state_against(self.conn, baseline)
        self.assertEqual(report["integrity_status"], "FAILED")
        self.assertEqual(report["missing_rows"], 1)
        self.assertEqual(report["unexpected_rows"], 1)
        self.assertEqual(report["primary_key_mismatches"], 1)
        self.assertEqual(report["samples"]["missing"], [["customers", "1"]])
        self.assertEqual(report["samples"]["unexpected"], [["customers", "99"]])
        self.assertEqual(report["samples"]["primary_key"], [["customers", "1", "99"]])

    def test_engine_rolls_back_when_checksum_verification_fails(self):
        anchor = change_tracker.latest_event_id(self.conn)
        self.conn.execute(
            "INSERT INTO inventory(sku, name, stock, price_cents) VALUES('SKU-2', 'Bad', 1, 10)")
        baseline = self.baseline()
        plan = recovery_engine.create_plan(self.conn, anchor_event_id=anchor)

        with self.assertRaises(RuntimeError):
            recovery_engine.execute_plan(self.conn, plan, reference=baseline)

        row = self.conn.execute("SELECT * FROM inventory WHERE sku = 'SKU-2'").fetchone()
        self.assertIsNotNone(row)
        run = self.conn.execute("SELECT status FROM recovery_runs ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(run["status"], "rolled-back")


    def test_checksum_is_stable_for_unchanged_state(self):
        first = verification.checksum_database(self.conn, db.TABLES)
        second = verification.checksum_database(self.conn, db.TABLES)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_checksum_covers_all_business_tables(self):
        self.conn.execute(
            "INSERT INTO orders(id,customer_id,total_cents,status,idem_key,created_at) "
            "VALUES(1,1,100,'paid','idem-1',1)")
        self.conn.execute(
            "INSERT INTO order_items(id,order_id,sku,qty,unit_cents) VALUES(1,1,'SKU-1',1,100)")
        baseline = self.baseline()

        self.conn.execute("UPDATE customers SET name='Changed' WHERE id=1")
        self.conn.execute("UPDATE inventory SET stock=5 WHERE sku='SKU-1'")
        self.conn.execute("UPDATE orders SET status='backorder' WHERE id=1")
        self.conn.execute("UPDATE order_items SET qty=2 WHERE id=1")
        report = verification.verify_state_against(self.conn, baseline)

        self.assertEqual(report["integrity_status"], "FAILED")
        self.assertEqual(report["mismatching_rows"], 4)
        self.assertEqual(
            sorted({entry[0] for entry in report["samples"]["modified"]}),
            ["customers", "inventory", "order_items", "orders"],
        )

    def test_checksum_scope_excludes_query_log(self):
        baseline = self.baseline()
        self.conn.execute(
            "INSERT INTO query_log(ts,source,sql,rows_affected) VALUES(1,'test','SELECT 1',0)")
        report = verification.verify_state_against(self.conn, baseline)
        self.assertEqual(report["integrity_status"], "VERIFIED")
        self.assertTrue(report["checksum_match"])
        self.assertNotIn("query_log", report["checked_tables"])


if __name__ == "__main__":
    unittest.main()

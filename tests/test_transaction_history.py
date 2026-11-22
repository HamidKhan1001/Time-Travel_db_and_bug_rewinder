import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timetravel import appcode, db
from timetravel.recovery import change_tracker, recovery_engine, transaction_logger


class TransactionHistoryTests(unittest.TestCase):
    def setUp(self):
        db.clock.offset = 0
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "history.db")
        self.conn = db.connect(self.path)
        db.create_schema(self.conn)

    def tearDown(self):
        db.clock.offset = 0
        self.conn.close()
        self.tmp.cleanup()

    def latest(self):
        return change_tracker.latest_event_id(self.conn)

    def committed(self, statements):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            for sql, params in statements:
                self.conn.execute(sql, params)
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def test_history_is_installed_and_only_captures_supported_tables(self):
        self.assertTrue(change_tracker.history_installed(self.conn))
        scope = change_tracker.capture_scope(db.TABLES)
        self.assertEqual(scope["tables"], sorted(db.TABLES))
        self.assertEqual(scope["operations"], ["I", "U", "D"])
        triggers = self.conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'recovery_%'").fetchone()[0]
        self.assertEqual(triggers, 12)

        before = self.latest()
        self.conn.execute("INSERT INTO query_log(ts, source, sql, rows_affected) VALUES(1, 'test', 'noop', 0)")
        self.conn.execute("CREATE TABLE scratch(x)")
        self.assertEqual(self.latest(), before)

    def test_autocommit_insert_records_required_fields(self):
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(1, 'Ada', 'ada@example.com')")
        events = change_tracker.fetch_events(self.conn, order="id ASC")
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.op, "I")
        self.assertEqual(event.tbl, "customers")
        self.assertEqual(event.pk, 1)
        self.assertEqual(event.pk_json, "1")
        self.assertEqual(event.event_seq, 1)
        self.assertIsNone(event.old_row())
        self.assertEqual(event.new_row()["name"], "Ada")
        self.assertGreater(event.transaction_id, 0)
        self.assertGreater(event.ts, 0)

        transactions = change_tracker.fetch_transactions(self.conn)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].id, event.transaction_id)
        self.assertGreater(transactions[0].started_at, 0)

    def test_storefront_crash_handler_is_captured(self):
        self.conn.execute(
            "INSERT INTO inventory(sku, name, stock, price_cents) VALUES('APX-0007', 'Bottle', 120, 2400)")
        self.conn.execute(
            "INSERT INTO inventory(sku, name, stock, price_cents) VALUES('APX-0042', 'Jacket', 35, 18900)")
        anchor = self.latest()
        result = appcode.fn("sync_stock")(self.conn, {"sku": "APX-0007", "stock": 0})
        self.assertEqual(result["updated_rows"], 2)
        events = change_tracker.fetch_events(self.conn, after_event_id=anchor, order="id ASC")
        self.assertEqual([event.tbl for event in events], ["inventory", "inventory"])
        self.assertEqual([event.op for event in events], ["U", "U"])
        self.assertEqual([event.event_seq for event in events], [1, 2])
        self.assertEqual(len({event.transaction_id for event in events}), 1)
        self.assertEqual(events[0].old_row()["stock"], 120)
        self.assertEqual(events[0].new_row()["stock"], 0)

    def test_explicit_transaction_groups_events_and_rollback_is_durable(self):
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(2, 'Ben', 'ben@example.com')")
        self.conn.execute(
            "INSERT INTO inventory(sku, name, stock, price_cents) VALUES('APX-0001', 'Item', 10, 100)")
        self.conn.execute("ROLLBACK")
        self.assertEqual(self.latest(), 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM recovery_transactions").fetchone()[0], 0)

        self.committed([
            ("INSERT INTO customers(id, name, email) VALUES(3, 'Cleo', 'cleo@example.com')", ()),
            ("INSERT INTO inventory(sku, name, stock, price_cents) VALUES('APX-0002', 'Item 2', 4, 200)", ()),
        ])
        events = change_tracker.fetch_events(self.conn, order="id ASC")
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].transaction_id, events[1].transaction_id)
        self.assertEqual([event.event_seq for event in events], [1, 2])

    def test_update_and_delete_capture_previous_and_new_values(self):
        self.conn.execute(
            "INSERT INTO inventory(sku, name, stock, price_cents) VALUES('APX-0001', 'Item', 10, 100)")
        anchor = self.latest()
        self.conn.execute("UPDATE inventory SET stock = 7 WHERE sku = 'APX-0001'")
        self.conn.execute("DELETE FROM inventory WHERE sku = 'APX-0001'")

        events = change_tracker.fetch_events(self.conn, after_event_id=anchor, order="id ASC")
        self.assertEqual([event.op for event in events], ["U", "D"])
        self.assertEqual(events[0].old_row()["stock"], 10)
        self.assertEqual(events[0].new_row()["stock"], 7)
        self.assertEqual(events[1].old_row()["stock"], 7)
        self.assertIsNone(events[1].new_row())
        self.assertNotEqual(events[0].transaction_id, events[1].transaction_id)

    def test_transaction_sequence_advances_in_committed_order(self):
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(1, 'Ada', 'ada@example.com')")
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(2, 'Ben', 'ben@example.com')")
        self.conn.execute("ROLLBACK")
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(3, 'Cleo', 'cleo@example.com')")
        ids = [transaction.id for transaction in change_tracker.fetch_transactions(self.conn)]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(set(ids)), len(ids))

    def test_event_id_anchor_survives_clock_skew(self):
        db.clock.offset = 100
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(1, 'Early', 'early@example.com')")
        anchor = self.latest()
        anchor_ts = change_tracker.fetch_events(self.conn, after_event_id=anchor - 1)[0].ts
        db.clock.offset = -100
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(2, 'Late', 'late@example.com')")
        events = change_tracker.fetch_events(self.conn, after_event_id=anchor, order="id ASC")
        self.assertEqual(len(events), 1)
        self.assertLess(events[0].ts, anchor_ts)

        plan = recovery_engine.create_plan(self.conn, anchor_event_id=anchor)
        plan_again = recovery_engine.create_plan(self.conn, anchor_event_id=anchor)
        self.assertEqual(plan.steps[0].event_id, events[0].id)
        self.assertEqual(plan.fingerprint(), plan_again.fingerprint())

    def test_recovery_plan_reverses_captured_changes_deterministically(self):
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(1, 'Ada', 'ada@example.com')")
        self.conn.execute(
            "INSERT INTO inventory(sku, name, stock, price_cents) VALUES('APX-0001', 'Item', 5, 100)")
        anchor = self.latest()
        self.committed([
            ("UPDATE inventory SET stock = 0 WHERE sku = 'APX-0001'", ()),
            ("DELETE FROM customers WHERE id = 1", ()),
        ])

        plan = recovery_engine.create_plan(self.conn, anchor_event_id=anchor)
        self.assertEqual([step.op for step in plan.steps], ["I", "U"])
        result = recovery_engine.execute_plan(self.conn, plan)
        self.assertTrue(all(check["ok"] for check in result["checks"]))
        self.assertEqual(self.conn.execute("SELECT stock FROM inventory WHERE sku = 'APX-0001'").fetchone()[0], 5)
        self.assertEqual(self.conn.execute("SELECT name FROM customers WHERE id = 1").fetchone()[0], "Ada")
        self.assertEqual(result["fingerprint"], plan.fingerprint())

    def test_failed_recovery_is_rolled_back(self):
        self.conn.execute("INSERT INTO customers(id, name, email) VALUES(1, 'Ada', 'ada@example.com')")
        plan = recovery_engine.create_plan(self.conn, anchor_event_id=0)
        self.conn.execute("DELETE FROM customers WHERE id = 1")
        marker = self.latest()
        with self.assertRaises(RuntimeError):
            recovery_engine.execute_plan(self.conn, plan)
        self.assertEqual(self.latest(), marker)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()

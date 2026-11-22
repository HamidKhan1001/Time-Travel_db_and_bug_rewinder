import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timetravel import agent, db, recovery_projection


class RecoveryProjectionTests(unittest.TestCase):
    def setUp(self):
        db.clock.offset = 0
        self.tmp = tempfile.TemporaryDirectory()
        self.original_live = db.LIVE
        self.original_connect = db.connect
        self.original_data = db.DATA
        self.original_pace = agent.PACE
        agent.PACE = 0
        db.LIVE = os.path.join(self.tmp.name, "live.db")
        db.DATA = self.tmp.name
        db.connect = lambda path=None: self.original_connect(db.LIVE if path is None else path)
        self.conn = db.connect(db.LIVE)
        db.create_schema(self.conn)
        db.clock.offset = -600
        self.conn.execute("INSERT INTO customers(id,name,email) VALUES(1,'Ada','ada@example.com')")
        self.conn.execute("INSERT INTO inventory(sku,name,stock,price_cents) VALUES('APX-0007','Bottle',0,100)")
        db.clock.offset = 0
        self.conn.execute(
            "INSERT INTO orders(id,customer_id,total_cents,status,idem_key,created_at) "
            "VALUES(1041,1,100,'paid','idem-1041',1)")
        self.conn.execute(
            "INSERT INTO order_items(id,order_id,sku,qty,unit_cents) VALUES(1,1041,'APX-0007',1,100)")

    def tearDown(self):
        self.conn.close()
        db.connect = self.original_connect
        db.LIVE = self.original_live
        db.DATA = self.original_data
        agent.PACE = self.original_pace
        db.clock.offset = 0
        self.tmp.cleanup()

    def _plan(self):
        return {
            "inventory_rows": [("APX-0007", "Bottle", 9, 100)],
            "customer_rows": [(2, "Grace", "grace@example.com")],
            "order_rows": [(1041, 1, 100, "paid", "idem-1041", 1),
                           (1042, 1, 200, "paid", "idem-1042", 2)],
            "item_rows": [(2, 1042, "APX-0007", 2, 100)],
            "backorder_ids": [1041],
        }

    def _summary(self):
        return {
            "dry_run_ok": True,
            "dry_run": [{"name": "Foreign keys intact", "ok": True, "detail": "0 violations"}],
            "conflicts": [{"kind": "oversell", "detail": "Order #1041 clamped"}],
            "risk": {"score": 8, "label": "LOW", "factors": []},
        }

    def _state_signature(self):
        return (
            self.conn.execute("SELECT COUNT(*) FROM changelog").fetchone()[0],
            self.conn.execute("SELECT sku, stock FROM inventory ORDER BY sku").fetchall(),
            self.conn.execute("SELECT id, status FROM orders ORDER BY id").fetchall(),
        )

    def test_preview_uses_real_plan_values_and_does_not_write(self):
        before = self._state_signature()
        preview = recovery_projection.build_preview(self.conn, self._plan(), self._summary(), sample_limit=50)
        self.assertEqual(before, self._state_signature())

        self.assertEqual(preview["label"], "PROPOSED RECOVERY PROJECTION — NOT APPLIED")
        self.assertEqual(preview["operation_counts"], {"INSERT": 3, "UPDATE": 2, "DELETE": 0})
        self.assertEqual(preview["tables"], ["customers", "inventory", "order_items", "orders"])
        by_id = {row["id"]: row for row in preview["rows"]}
        self.assertEqual(by_id["inventory:APX-0007:stock"]["before"], 0)
        self.assertEqual(by_id["inventory:APX-0007:stock"]["after"], 9)
        self.assertEqual(by_id["inventory:APX-0007:stock"]["operation"], "UPDATE")
        self.assertEqual(by_id["orders:1041:status"]["before"], "paid")
        self.assertEqual(by_id["orders:1041:status"]["after"], "backorder")
        self.assertEqual(by_id["orders:1042:record"]["operation"], "INSERT")
        self.assertNotIn("email", by_id["customers:2:record"]["after"])
        self.assertEqual(preview["validation"]["dry_run_ok"], True)
        self.assertEqual(preview["validation"]["checks"][0]["name"], "Foreign keys intact")
        self.assertEqual(len(preview["conflicts"]), 1)

    def test_preview_sample_is_bounded_but_counts_cover_full_plan(self):
        plan = self._plan()
        plan["inventory_rows"] = [(f"SKU-{index:04d}", "Item", 5, 10) for index in range(30)]
        preview = recovery_projection.build_preview(self.conn, plan, self._summary(), sample_limit=5)
        self.assertEqual(len(preview["rows"]), 5)
        self.assertEqual(preview["row_count"], 34)
        self.assertTrue(preview["sample_truncated"])

    def test_capture_actual_reads_post_recovery_values_and_marks_missing_rows(self):
        preview = recovery_projection.build_preview(self.conn, self._plan(), self._summary(), sample_limit=50)
        self.conn.execute("UPDATE inventory SET stock=9 WHERE sku='APX-0007'")
        self.conn.execute("UPDATE orders SET status='backorder' WHERE id=1041")
        actual = recovery_projection.capture_actual(self.conn, preview)
        self.assertEqual(actual["values"]["inventory:APX-0007:stock"], 9)
        self.assertEqual(actual["values"]["orders:1041:status"], "backorder")
        missing = dict(preview)
        missing["rows"] = [{"id": "orders:9999:record", "table": "orders", "key": "9999", "field": "record", "after": {"id": 9999}}]
        unavailable = recovery_projection.capture_actual(self.conn, missing)["values"]
        self.assertIn("unavailable", unavailable["orders:9999:record"])

    def test_verification_status_is_derived_from_actual_checks_only(self):
        passed = recovery_projection.build_verification(
            [{"name": "Foreign keys intact", "ok": True, "detail": "0 violations"}], completed_at=5)
        self.assertEqual(passed["status"], "passed")
        self.assertEqual(passed["completed_at"], 5)
        self.assertEqual(passed["checksum"]["status"], "unavailable")
        failed = recovery_projection.build_verification(
            [{"name": "Foreign keys intact", "ok": False, "detail": "1 violation"}])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(recovery_projection.build_verification([])["status"], "unavailable")

    def test_session_json_exposes_new_projection_fields(self):
        session = agent.Session("projection contract")
        session.recovery_preview = {"rows": []}
        session.actual_recovery = {"values": {}}
        session.verification = {"status": "passed", "checks": []}
        session.undo_state = recovery_projection.initial_undo_state()
        payload = session.to_json()
        for key in ("recovery_preview", "actual_recovery", "verification", "undo_state"):
            self.assertIn(key, payload)
        self.assertFalse(payload["undo_state"]["available"])

    def test_agent_pipeline_exposes_preview_then_actual_verification_and_undo(self):
        session = None
        now = db.clock.now()
        self.conn.execute(
            "INSERT INTO query_log(ts,source,sql,rows_affected) VALUES(?,?,?,?)",
            (now - 30, "/api/admin/sync-stock", "UPDATE inventory SET stock = ?", 100))
        self.conn.execute(
            "INSERT INTO orders(id,customer_id,total_cents,status,idem_key,created_at) "
            "VALUES(1043,1,100,'paid','idem-1043',?)", (now,))

        try:
            session = agent.start("Take the business back to 2 minutes ago, keep the order", background=False)
            self.assertEqual(session.phase, "awaiting_approval", [event["msg"] for event in session.events])
            pending = session.to_json()
            self.assertIsNotNone(pending["recovery_preview"])
            self.assertIsNone(pending["actual_recovery"])
            self.assertIsNone(pending["verification"])
            self.assertFalse(pending["undo_state"]["available"])

            before_preview_render = self._state_signature()
            recovery_projection.build_preview(
                self.conn, session.internal["plan"], session.plan)
            self.assertEqual(before_preview_render, self._state_signature())

            agent.approve(session.id)
            applied = session.to_json()
            self.assertEqual(session.phase, "applied")
            self.assertIsNotNone(applied["actual_recovery"])
            self.assertEqual(applied["verification"]["status"], "passed")
            self.assertTrue(applied["undo_state"]["available"])

            agent.undo(session.id)
            undone = session.to_json()
            self.assertEqual(session.phase, "undone")
            self.assertTrue(undone["undo_state"]["succeeded"])
            self.assertFalse(undone["undo_state"]["available"])
        finally:
            if session is not None:
                agent.SESSIONS.pop(session.id, None)


if __name__ == "__main__":
    unittest.main()

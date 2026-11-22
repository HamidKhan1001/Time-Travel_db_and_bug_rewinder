import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timetravel import agent, audit, db
from timetravel.recovery import change_tracker, recovery_engine


class AuditPersistenceTests(unittest.TestCase):
    def setUp(self):
        db.clock.offset = 0
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "audit.db")

    def tearDown(self):
        db.clock.offset = 0
        self.tmp.cleanup()

    def test_successful_event_survives_connection_reopen(self):
        conn = db.connect(self.path)
        audit_id = audit.record_event(
            conn,
            "INC-TEST01",
            "recovery_completed",
            "completed",
            {"code_patched": True, "restored_rows": 3},
        )
        conn.close()

        reopened = db.connect(self.path)
        try:
            events = audit.read_session_events(reopened, "INC-TEST01")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["id"], audit_id)
            self.assertEqual(events[0]["event_type"], "recovery_completed")
            self.assertEqual(events[0]["status"], "completed")
            self.assertTrue(events[0]["detail"]["code_patched"])
            self.assertEqual(events[0]["detail"]["restored_rows"], 3)
        finally:
            reopened.close()

    def test_failed_approval_and_undo_events_are_distinct(self):
        conn = db.connect(self.path)
        audit.record_event(conn, "INC-TEST02", "approval_rejected", "rejected", {"current_phase": "applied"})
        audit.record_event(conn, "INC-TEST02", "undo_failed", "failed", {"detail": "snapshot missing"})
        conn.close()

        reopened = db.connect(self.path)
        try:
            events = audit.read_session_events(reopened, "INC-TEST02")
            self.assertEqual([event["event_type"] for event in events], ["approval_rejected", "undo_failed"])
            self.assertEqual([event["status"] for event in events], ["rejected", "failed"])
        finally:
            reopened.close()

    def test_unknown_session_has_no_audit_events(self):
        conn = db.connect(self.path)
        try:
            self.assertEqual(audit.read_session_events(conn, "INC-MISSING"), ())
        finally:
            conn.close()

    def test_invalid_status_and_missing_identity_are_rejected(self):
        conn = db.connect(self.path)
        try:
            with self.assertRaises(ValueError):
                audit.record_event(conn, "INC-TEST03", "recovery_completed", "success", {})
            with self.assertRaises(ValueError):
                audit.record_event(conn, "", "recovery_completed", "completed", {})
        finally:
            conn.close()

    def test_closed_database_write_is_not_silently_ignored(self):
        conn = db.connect(self.path)
        conn.close()
        with self.assertRaises(sqlite3.ProgrammingError):
            audit.record_event(conn, "INC-TEST04", "recovery_completed", "completed", {})

    def test_malformed_stored_detail_is_read_safely(self):
        conn = db.connect(self.path)
        audit.ensure_schema(conn)
        conn.execute(
            "INSERT INTO session_audit_events(session_id,event_type,status,ts,detail_json) "
            "VALUES(?,?,?,?,?)",
            ("INC-TEST05", "recovery_failed", "failed", db.clock.now(), "not-json"),
        )
        conn.close()

        reopened = db.connect(self.path)
        try:
            event = audit.read_session_events(reopened, "INC-TEST05")[0]
            self.assertEqual(event["detail"], {"detail_json_error": "stored detail is not valid JSON"})
        finally:
            reopened.close()

    def test_agent_session_events_persist_after_recorded_and_reopened(self):
        original_live = db.LIVE
        original_connect = db.connect
        db.LIVE = self.path
        db.connect = lambda path=None: original_connect(db.LIVE if path is None else path)
        conn = db.connect(db.LIVE)
        db.create_schema(conn)
        conn.close()
        try:
            session = agent.Session("test audit session")
            agent.SESSIONS[session.id] = session
            agent._record_audit(session, "recovery_initiated", "started", {"prompt_length": 18})

            reopened = db.connect(self.path)
            try:
                events = audit.read_session_events(reopened, session.id)
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["event_type"], "recovery_initiated")
            finally:
                reopened.close()
            agent.SESSIONS.pop(session.id, None)
        finally:
            db.connect = original_connect
            db.LIVE = original_live

    def test_successful_recovery_run_survives_reopen(self):
        conn = db.connect(self.path)
        db.create_schema(conn)
        conn.execute("INSERT INTO inventory(sku,name,stock,price_cents) VALUES('A','Item',10,100)")
        anchor = change_tracker.latest_event_id(conn)
        conn.execute("UPDATE inventory SET stock=0 WHERE sku='A'")
        plan = recovery_engine.create_plan(conn, anchor_event_id=anchor, transaction_ids=None)
        result = recovery_engine.execute_plan(conn, plan)
        conn.close()

        reopened = db.connect(self.path)
        try:
            run = reopened.execute(
                "SELECT status,step_count,detail FROM recovery_runs WHERE id=?",
                (result["audit_run_id"],),
            ).fetchone()
            self.assertEqual(run["status"], "committed")
            self.assertEqual(run["step_count"], 1)
            actions = reopened.execute(
                "SELECT status,tbl FROM recovery_actions WHERE run_id=?",
                (result["audit_run_id"],),
            ).fetchall()
            self.assertTrue(actions)
            self.assertEqual({tuple(action) for action in actions}, {("applied", "inventory")})
        finally:
            reopened.close()

    def test_failed_recovery_conflict_creates_rolled_back_audit_run(self):
        conn = db.connect(self.path)
        db.create_schema(conn)
        conn.execute("INSERT INTO inventory(sku,name,stock,price_cents) VALUES('A','Item',10,100)")
        anchor = change_tracker.latest_event_id(conn)
        conn.execute("UPDATE inventory SET stock=0 WHERE sku='A'")
        conn.execute("UPDATE inventory SET stock=5 WHERE sku='A'")
        plan = recovery_engine.create_plan(conn, anchor_event_id=anchor)

        from timetravel.recovery.integrity import RecoveryConflictError
        with self.assertRaises(RecoveryConflictError):
            recovery_engine.execute_plan(conn, plan)

        run = conn.execute(
            "SELECT id,status,detail FROM recovery_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        run_id = run["id"]
        self.assertEqual(run["status"], "rolled-back")
        self.assertIn("changed after", run["detail"])
        conn.close()

        reopened = db.connect(self.path)
        try:
            reopened_run = reopened.execute(
                "SELECT status,detail FROM recovery_runs WHERE id=?", (run_id,)
            ).fetchone()
            self.assertEqual(reopened_run["status"], "rolled-back")
            self.assertIn("changed after", reopened_run["detail"])
        finally:
            reopened.close()

    def test_historical_audit_is_readable_after_session_object_removed(self):
        original_live = db.LIVE
        original_connect = db.connect
        db.LIVE = self.path
        db.connect = lambda path=None: original_connect(db.LIVE if path is None else path)
        conn = db.connect(db.LIVE)
        db.create_schema(conn)
        conn.close()
        try:
            session = agent.Session("historical audit")
            agent.SESSIONS[session.id] = session
            agent._record_audit(session, "recovery_completed", "completed", {"code_patched": True})
            agent.SESSIONS.pop(session.id, None)

            reopened = db.connect(self.path)
            try:
                events = agent.audit_events(session.id)
                self.assertEqual([event["event_type"] for event in events], ["recovery_completed"])
            finally:
                reopened.close()
        finally:
            db.connect = original_connect
            db.LIVE = original_live


if __name__ == "__main__":
    unittest.main()

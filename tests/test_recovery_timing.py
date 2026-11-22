import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timetravel import agent, audit, db


class RecoveryTimingTests(unittest.TestCase):
    def setUp(self):
        db.clock.offset = 0
        self.tmp = tempfile.TemporaryDirectory()
        self.original_live = db.LIVE
        self.original_connect = db.connect
        self.original_pace = agent.PACE
        db.LIVE = os.path.join(self.tmp.name, "timing.db")
        db.connect = lambda path=None: self.original_connect(db.LIVE if path is None else path)
        agent.PACE = 0
        conn = db.connect(db.LIVE)
        db.create_schema(conn)
        conn.close()

    def tearDown(self):
        agent.SESSIONS.clear()
        db.connect = self.original_connect
        db.LIVE = self.original_live
        agent.PACE = self.original_pace
        db.clock.offset = 0
        self.tmp.cleanup()

    def _session(self, phase="awaiting_approval"):
        session = agent.Session("timing test")
        session.phase = phase
        session.plan = {"risk": {"score": 0}, "order_ids": []}
        session.internal = {"plan": {}, "expected": {}, "live_marker": 0}
        session.recovery_preview = {"rows": []}
        agent.SESSIONS[session.id] = session
        return session

    def test_new_session_timings_are_unavailable(self):
        session = agent.Session("new timing contract")
        report = session.timing_report()
        expected = {
            "planning_preview_seconds": None,
            "approval_delay_seconds": None,
            "recovery_execution_seconds": None,
            "verification_seconds": None,
            "undo_seconds": None,
            "total_workflow_seconds": None,
        }
        self.assertEqual(report, expected)
        self.assertEqual(session.to_json()["timings"], expected)

    def test_timing_report_uses_monotonic_anchors_without_wall_clock(self):
        session = agent.Session("anchor timing contract")
        session._workflow_started = 10.0
        session._approval_accepted = 10.0
        session._execution_started = 10.25
        session._workflow_finished = 14.0
        report = session.timing_report()
        self.assertEqual(report["approval_delay_seconds"], 0.25)
        self.assertAlmostEqual(report["total_workflow_seconds"], 4.0, places=12)

    def test_apply_failure_records_execution_timing_and_audit(self):
        session = self._session()
        with mock.patch.object(agent, "_monotonic", side_effect=[10.0, 10.5, 10.8]), \
                mock.patch.object(agent.tools, "apply_recovery_tool", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                agent.approve(session.id)

        self.assertEqual(session.phase, "awaiting_approval")
        self.assertAlmostEqual(session.timing_report()["approval_delay_seconds"], 0.5, places=12)
        self.assertAlmostEqual(session.timings["recovery_execution_seconds"], 0.3, places=12)
        self.assertIsNone(session.timings["verification_seconds"])
        conn = db.connect(db.LIVE)
        try:
            events = audit.read_session_events(conn, session.id)
        finally:
            conn.close()
        failed = [event for event in events if event["event_type"] == "recovery_failed"]
        self.assertEqual(len(failed), 1)
        self.assertAlmostEqual(
            failed[0]["detail"]["timings"]["recovery_execution_seconds"], 0.3, places=12)

    def test_undo_success_records_undo_timing_and_audit(self):
        session = self._session(phase="applied")
        with mock.patch.object(agent, "_monotonic", side_effect=[20.0, 20.4]), \
                mock.patch.object(agent.tools, "undo_recovery", return_value=None):
            agent.undo(session.id)

        self.assertEqual(session.phase, "undone")
        self.assertAlmostEqual(session.timings["undo_seconds"], 0.4, places=12)
        self.assertIsNone(session.timing_report()["total_workflow_seconds"])
        conn = db.connect(db.LIVE)
        try:
            events = audit.read_session_events(conn, session.id)
        finally:
            conn.close()
        completed = [event for event in events if event["event_type"] == "undo_completed"]
        self.assertEqual(len(completed), 1)
        self.assertAlmostEqual(completed[0]["detail"]["timings"]["undo_seconds"], 0.4, places=12)


if __name__ == "__main__":
    unittest.main()

import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.error
import urllib.request
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server
from timetravel import audit, db, sse


class SSETests(unittest.TestCase):
    def setUp(self):
        db.clock.offset = 0
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "sse.db")
        self.original_connect = db.connect
        self.original_live = db.LIVE
        db.LIVE = self.path
        db.connect = lambda path=None: self.original_connect(db.LIVE if path is None else path)

    def tearDown(self):
        db.connect = self.original_connect
        db.LIVE = self.original_live
        db.clock.offset = 0
        self.tmp.cleanup()

    def test_sse_frame_schema_and_named_event(self):
        record = {
            "id": 17,
            "session_id": "INC-A1B2C3",
            "event_type": "recovery_completed",
            "status": "completed",
            "ts": 1795340000.0,
            "detail": {"code_patched": True},
        }
        name, event_id, frame = sse.audit_event_to_sse(record)
        self.assertEqual(name, "recovery_completed")
        self.assertEqual(event_id, "17")
        self.assertIn("id: 17\n", frame)
        self.assertIn("event: recovery_completed\n", frame)
        self.assertIn('"session_id":"INC-A1B2C3"', frame)
        self.assertIn('"payload":{"code_patched":true}', frame)

    def test_last_event_id_validation_and_session_validation(self):
        self.assertEqual(sse.parse_last_event_id(None), 0)
        self.assertEqual(sse.parse_last_event_id("42"), 42)
        with self.assertRaises(ValueError):
            sse.parse_last_event_id("bad")
        with self.assertRaises(ValueError):
            sse.parse_last_event_id("-1")
        self.assertTrue(sse.validate_session_id("INC-A1B2C3"))
        self.assertFalse(sse.validate_session_id("../other"))

    def test_replay_is_session_scoped_and_ordered(self):
        conn = db.connect(self.path)
        first = audit.record_event(conn, "INC-A1B2C3", "recovery_initiated", "started", {})
        audit.record_event(conn, "INC-D4E5F6", "recovery_initiated", "started", {})
        second = audit.record_event(conn, "INC-A1B2C3", "recovery_completed", "completed", {})
        conn.close()

        first_page = sse.read_events_after("INC-A1B2C3", 0)
        self.assertEqual([record["id"] for record in first_page], [first, second])
        second_page = sse.read_events_after("INC-A1B2C3", first)
        self.assertEqual([record["id"] for record in second_page], [second])

    def test_new_event_during_replay_is_delivered_once_in_live_phase(self):
        first = {"id": 10, "session_id": "INC-A1B2C3", "event_type": "recovery_initiated", "status": "started", "ts": 1.0, "detail": {}}
        second = {"id": 11, "session_id": "INC-A1B2C3", "event_type": "recovery_completed", "status": "completed", "ts": 2.0, "detail": {}}
        live_state = []

        def controlled_read(session_id, after_id):
            self.assertEqual(session_id, "INC-A1B2C3")
            if after_id == 0:
                return [first]
            if after_id == 10:
                return list(live_state)
            return []

        with mock.patch.object(sse, "read_events_after", side_effect=controlled_read):
            frames = sse.iter_sse_frames(
                "INC-A1B2C3", 0,
                heartbeat_seconds=60.0,
                poll_seconds=0,
                max_seconds=0.1,
            )
            replay = next(frames)
            self.assertIn("id: 10", replay)

            live_state.append(second)
            live = next(frames)
            self.assertIn("id: 11", live)
            remaining = list(frames)
            self.assertFalse(any("id: 10" in frame for frame in remaining))

    def test_http_sse_valid_subscription_and_content_type(self):
        conn = db.connect(self.path)
        audit.record_event(conn, "INC-A1B2C3", "recovery_initiated", "started", {})
        conn.close()

        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        port = httpd.server_address[1]
        try:
            response = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/session/INC-A1B2C3/events",
                timeout=2,
            )
            self.assertEqual(response.status, 200)
            self.assertTrue(response.headers["Content-Type"].startswith("text/event-stream"))
            first = response.readline().decode("utf-8").strip()
            self.assertIn("retry:", first)
            response.close()
            time.sleep(0.2)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_http_sse_unknown_and_invalid_ids(self):
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        port = httpd.server_address[1]
        try:
            for url, status in (
                (f"http://127.0.0.1:{port}/api/session/INC-Z9Y8X7/events", 404),
                (f"http://127.0.0.1:{port}/api/session/../events", 400),
                (f"http://127.0.0.1:{port}/api/session/INC-A1B2C3/events?last_event_id=bad", 400),
            ):
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(url, timeout=2)
                self.assertEqual(raised.exception.code, status)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_heartbeat_format(self):
        heartbeat = sse.format_heartbeat(1795340000.0)
        self.assertEqual(heartbeat, ": heartbeat 1795340000.000\n\n")

    def test_stream_error_frame_is_safe(self):
        frame = sse.format_stream_error()
        self.assertIn("event: stream_error", frame)
        self.assertIn("audit stream unavailable", frame)

    def test_lifecycle_event_names_are_stable(self):
        expected = {
            "recovery_initiated": "session_started",
            "recovery_preview_generated": "preview_generated",
            "approval_granted": "approval_granted",
            "approval_rejected": "approval_rejected",
            "recovery_execution_started": "recovery_started",
            "integrity_verified": "integrity_verified",
            "recovery_completed": "recovery_completed",
            "recovery_failed": "recovery_failed",
            "undo_initiated": "undo_started",
            "undo_completed": "undo_completed",
            "undo_failed": "undo_failed",
            "undo_rejected": "undo_failed",
        }
        self.assertEqual(sse.EVENT_NAMES, expected)

    def test_malformed_audit_detail_is_safely_exposed_as_payload_error_marker(self):
        conn = db.connect(self.path)
        audit.ensure_schema(conn)
        conn.execute(
            "INSERT INTO session_audit_events(session_id,event_type,status,ts,detail_json) VALUES(?,?,?,?,?)",
            ("INC-A1B2C3", "recovery_failed", "failed", db.clock.now(), "not-json"),
        )
        conn.close()
        record = sse.read_events_after("INC-A1B2C3", 0)[0]
        name, _, frame = sse.audit_event_to_sse(record)
        self.assertEqual(name, "recovery_failed")
        self.assertIn("detail_json_error", frame)

    def test_frontend_uses_eventsource_and_stable_id_deduplication(self):
        html_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "index.html")
        with open(html_path, "r", encoding="utf-8") as handle:
            html = handle.read()
        self.assertIn("new EventSource('/api/session/'", html)
        self.assertIn("sseSeen", html)
        self.assertIn("source.close()", html)

    def test_stream_bounds_and_heartbeat_constants(self):
        self.assertEqual(sse.HEARTBEAT_SECONDS, 15.0)
        self.assertEqual(sse.MAX_STREAM_SECONDS, 300.0)

    def test_initial_replay_database_error_is_safe_stream_error(self):
        with mock.patch.object(sse, "read_events_after", side_effect=sqlite3.OperationalError("database unavailable")):
            frames = list(sse.iter_sse_frames("INC-A1B2C3", 0, max_seconds=0.1))
        self.assertEqual(frames, [sse.format_stream_error()])


if __name__ == "__main__":
    unittest.main()

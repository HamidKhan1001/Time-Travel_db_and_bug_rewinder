"""Audit list/summary endpoints, discard, audit survival across undo, CORS, and the patched flag."""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server
from timetravel import agent, appcode, audit, db


class AuditApiTests(unittest.TestCase):
    def setUp(self):
        db.clock.offset = 0
        self.tmp = tempfile.TemporaryDirectory()
        self.original = (db.LIVE, db.DATA, db.connect)
        db.LIVE = os.path.join(self.tmp.name, "live.db")
        db.DATA = self.tmp.name
        orig = self.original[2]
        db.connect = lambda path=None: orig(db.LIVE if path is None else path)
        conn = db.connect(db.LIVE)
        db.create_schema(conn)
        conn.close()
        appcode.reload()

    def tearDown(self):
        agent.SESSIONS.clear()
        db.LIVE, db.DATA, db.connect = self.original
        self.tmp.cleanup()

    def record(self, sid, event, status, detail=None):
        conn = db.connect()
        audit.record_event(conn, sid, event, status, detail)
        conn.close()

    def summaries(self):
        conn = db.connect()
        try:
            return audit.summarize_recoveries(conn)
        finally:
            conn.close()

    def finished_session(self, sid, terminal, status, prompt="rewind 2 minutes ago"):
        self.record(sid, "recovery_initiated", "started", {"prompt": prompt})
        self.record(sid, "recovery_preview_generated", "started", {
            "orders_preserved": 3, "discarded_rows": 1420, "conflict_count": 1, "risk_score": 25,
            "rewind_target_ts": 1000.0})
        self.record(sid, terminal, status, {"timings": {"total_workflow_seconds": 4.26}})

    def test_summary_lists_only_finished_sessions_newest_first(self):
        self.finished_session("INC-AAA111", "recovery_completed", "completed")
        self.finished_session("INC-BBB222", "recovery_discarded", "rejected")
        self.record("INC-CCC333", "recovery_initiated", "started", {"prompt": "still running"})
        rows = self.summaries()
        self.assertEqual([r["id"] for r in rows], ["INC-BBB222", "INC-AAA111"])
        applied = rows[1]
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(applied["delta"], {"kept": 3, "discarded": 1420, "conflicts": 1})
        self.assertEqual(applied["risk"], 0.25)
        self.assertEqual(applied["durationSec"], 4.3)
        self.assertEqual(applied["rowsLost"], 0)
        self.assertIsNone(rows[0]["rowsLost"])          # a discarded plan makes no claim about rows

    def test_latest_terminal_event_wins(self):
        self.finished_session("INC-AAA111", "recovery_failed", "failed")
        self.record("INC-AAA111", "recovery_completed", "completed", {})
        self.assertEqual(self.summaries()[0]["status"], "applied")
        self.record("INC-AAA111", "undo_completed", "completed", {})
        self.assertEqual(self.summaries()[0]["status"], "undone")

    def test_filter_and_stats(self):
        self.finished_session("INC-AAA111", "recovery_completed", "completed", prompt="nightly feed")
        self.finished_session("INC-BBB222", "recovery_failed", "failed", prompt="other thing")
        self.finished_session("INC-CCC333", "recovery_discarded", "rejected")
        rows = self.summaries()
        self.assertEqual([r["id"] for r in audit.filter_recoveries(rows, search="nightly")], ["INC-AAA111"])
        self.assertEqual(len(audit.filter_recoveries(rows, status="failed")), 1)
        stats = audit.recovery_stats(rows)
        self.assertEqual(stats["totalRecoveries"], 3)
        self.assertEqual(stats["successRate"], 50.0)    # discarded plans are not counted either way
        self.assertIsNone(audit.recovery_stats([])["successRate"])

    def test_restore_events_keeps_ids_after_snapshot_replaces_db(self):
        self.record("INC-AAA111", "recovery_initiated", "started", {})
        conn = db.connect()
        saved = list(audit.read_events(conn))
        conn.execute("DELETE FROM session_audit_events")
        audit.restore_events(conn, saved)
        self.assertEqual([e["id"] for e in audit.read_events(conn)], [e["id"] for e in saved])
        conn.close()

    def test_discard_only_from_awaiting_approval_and_never_touches_data(self):
        session = agent.Session("rewind 2 minutes ago")
        agent.SESSIONS[session.id] = session
        with self.assertRaises(ValueError):
            agent.discard(session.id)
        session.phase = "awaiting_approval"
        agent.discard(session.id)
        self.assertEqual(session.phase, "discarded")
        self.assertEqual(self.summaries()[0]["status"], "discarded")
        with self.assertRaises(ValueError):
            agent.approve(session.id)

    def serve(self):
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close(), thread.join(timeout=2)))
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def get(self, url, origin=None):
        request = urllib.request.Request(url, headers={"Origin": origin} if origin else {})
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.loads(response.read()), response.headers

    def test_http_audit_routes_and_pagination(self):
        for i in range(7):
            self.finished_session(f"INC-AB{i}000", "recovery_completed", "completed")
        base = self.serve()
        body, _ = self.get(f"{base}/api/audit?page=2&pageSize=5")
        self.assertEqual((body["total"], len(body["items"]), body["page"]), (7, 2, 2))
        summary, _ = self.get(f"{base}/api/audit/summary")
        self.assertEqual(summary["totalRecoveries"], 7)
        one, _ = self.get(f"{base}/api/audit/INC-AB0000")
        self.assertEqual(one["status"], "applied")
        with self.assertRaises(urllib.error.HTTPError) as missing:
            self.get(f"{base}/api/audit/INC-NOPE")
        self.assertEqual(missing.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError) as bad:
            self.get(f"{base}/api/audit?page=abc")
        self.assertEqual(bad.exception.code, 400)

    def test_cors_only_for_localhost_origins(self):
        base = self.serve()
        _, headers = self.get(f"{base}/api/audit/summary", origin="http://localhost:5173")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://localhost:5173")
        _, headers = self.get(f"{base}/api/audit/summary", origin="https://evil.example")
        self.assertIsNone(headers["Access-Control-Allow-Origin"])
        preflight = urllib.request.Request(f"{base}/api/rewind", method="OPTIONS",
                                           headers={"Origin": "http://127.0.0.1:5173"})
        with urllib.request.urlopen(preflight, timeout=3) as response:
            self.assertEqual(response.status, 204)
            self.assertIn("POST", response.headers["Access-Control-Allow-Methods"])

    def test_app_route_serves_404_message_when_not_built_and_blocks_traversal(self):
        base = self.serve()
        original = server.APP_DIR
        server.APP_DIR = os.path.join(self.tmp.name, "dist")
        self.addCleanup(setattr, server, "APP_DIR", original)
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.get(f"{base}/app/")
        self.assertEqual(raised.exception.code, 404)
        os.makedirs(server.APP_DIR)
        with open(os.path.join(server.APP_DIR, "index.html"), "w") as handle:
            handle.write("<html>shell</html>")
        with open(os.path.join(self.tmp.name, "secret.txt"), "w") as handle:
            handle.write("secret")
        with urllib.request.urlopen(f"{base}/app/audit-log", timeout=3) as response:   # client-side route -> shell
            self.assertIn(b"shell", response.read())
        for path in ("/app/..%2fsecret.txt", "/app/%2e%2e/secret.txt", "/app/missing.js"):
            with self.assertRaises(urllib.error.HTTPError, msg=path) as blocked:
                urllib.request.urlopen(f"{base}{path}", timeout=3)
            self.assertEqual(blocked.exception.code, 404, path)

    def test_patched_flag_is_false_for_the_buggy_handler(self):
        # place_order() already contains "WHERE sku = ?"; that must not read as "bug fixed".
        self.assertFalse(server.api_state()["patched"])


if __name__ == "__main__":
    unittest.main()

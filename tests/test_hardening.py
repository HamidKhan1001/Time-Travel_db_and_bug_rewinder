"""Server hardening and durability: body limits, stream cap, WAL, indexes, retention, session eviction."""
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness

from timetravel import agent, appcode, db, seed
from timetravel.web.maintenance import Maintenance
from timetravel.web.routes import state as state_routes


class IsolatedDB(unittest.TestCase):
    """A throwaway live.db, with the connect() hook the other test modules use."""

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


class HttpHardeningTests(IsolatedDB):
    def setUp(self):
        super().setUp()
        self.running = harness.start_server()
        self.ctx = self.running.ctx
        self.port = self.running.port

    def tearDown(self):
        self.running.stop()
        super().tearDown()

    def call(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, None

    def test_oversized_body_is_rejected_with_413_before_reading_it(self):
        self.ctx.reconfigure(max_body_bytes=100)
        status, body = self.call("POST", "/api/rewind", body=json.dumps({"prompt": "x" * 500}),
                                 headers={"Content-Type": "application/json"})
        self.assertEqual(status, 413)
        self.assertIn("too large", body["error"])

    def test_body_at_the_limit_is_accepted(self):
        payload = json.dumps({"sku": "NOPE", "stock": 1})
        self.ctx.reconfigure(max_body_bytes=len(payload))
        status, _ = self.call("POST", "/api/admin/sync-stock", body=payload)
        self.assertNotEqual(status, 413)

    def test_invalid_json_and_non_object_bodies_are_400(self):
        for raw in ("{not json", "[1, 2]", '"text"', "123"):
            status, body = self.call("POST", "/api/rewind", body=raw)
            self.assertEqual(status, 400, raw)
            self.assertIn("error", body)

    def test_negative_or_garbage_content_length_is_400(self):
        for value in ("-5", "abc", "1e3"):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
            c.putrequest("POST", "/api/rewind")
            c.putheader("Content-Length", value)
            c.endheaders()
            r = c.getresponse()
            r.read()
            c.close()
            self.assertEqual(r.status, 400, value)

    def test_unhandled_error_does_not_leak_internals(self):
        with mock.patch.object(state_routes, "build_state", side_effect=RuntimeError("secret /path/to/db failure")):
            status, body = self.call("GET", "/api/state")
        self.assertEqual(status, 500)
        self.assertEqual(body["error"], "internal error")
        self.assertNotIn("secret", json.dumps(body))
        self.assertTrue(body["request_id"])

    def test_sse_streams_are_capped_with_503_and_slots_are_released(self):
        agent.start("restore inventory to before the crash", background=False)
        sid = next(iter(agent.SESSIONS))
        sem = threading.BoundedSemaphore(1)
        sem.acquire()                                    # every slot taken
        self.ctx.sse_slots = sem
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        c.request("GET", f"/api/session/{sid}/events")
        r = c.getresponse()
        r.read()
        c.close()
        self.assertEqual(r.status, 503)
        self.assertEqual(r.getheader("Retry-After"), "5")

    def test_favicon_ico_redirects_to_the_svg(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        c.request("GET", "/favicon.ico")
        r = c.getresponse()
        r.read()
        c.close()
        self.assertEqual((r.status, r.getheader("Location")), (302, "/app/favicon.svg"))


class DatabaseDurabilityTests(IsolatedDB):
    def test_file_databases_use_wal_and_memory_databases_do_not_break(self):
        c = db.connect(db.LIVE)
        self.assertEqual(c.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        c.close()
        m = db.connect(":memory:")
        self.assertEqual(m.execute("PRAGMA journal_mode").fetchone()[0], "memory")
        m.close()

    def test_changelog_ts_index_exists_and_is_used(self):
        c = db.connect(db.LIVE)
        plan = " ".join(r[3] for r in c.execute("EXPLAIN QUERY PLAN SELECT * FROM changelog WHERE id IN (SELECT id FROM changelog WHERE ts > 1) ORDER BY id DESC"))
        self.assertIn("ix_changelog_ts", plan)
        c.close()

    def test_changes_after_returns_newest_first_and_only_later_rows(self):
        c = db.connect(db.LIVE)
        self._fill(c, 20)                                   # ts = 0..19
        rows = db.changes_after(c, 14.5)
        self.assertEqual([r["ts"] for r in rows], [19.0, 18.0, 17.0, 16.0, 15.0])
        self.assertEqual([r["id"] for r in rows], sorted((r["id"] for r in rows), reverse=True))
        c.close()

    def test_ensure_indexes_upgrades_an_old_database_and_is_idempotent(self):
        c = db.connect(db.LIVE)
        c.execute("DROP INDEX ix_changelog_ts")
        db.ensure_indexes(c)
        db.ensure_indexes(c)
        self.assertTrue(c.execute("SELECT 1 FROM sqlite_master WHERE name='ix_changelog_ts'").fetchone())
        c.close()

    def _fill(self, c, n):
        c.execute("BEGIN")
        c.executemany("INSERT INTO changelog(ts,tbl,op,pk,old,new) VALUES(?,?,?,?,?,?)",
                      [(float(i), "inventory", "U", i, "{}", "{}") for i in range(n)])
        c.execute("COMMIT")

    def test_prune_keeps_newest_rows_and_last_change_id_is_unchanged(self):
        c = db.connect(db.LIVE)
        self._fill(c, 1000)
        before = db.last_change_id(c)
        deleted = db.prune_changelog(c, 250, batch=100)
        self.assertEqual(deleted, 750)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM changelog").fetchone()[0], 250)
        self.assertEqual(c.execute("SELECT MIN(id) FROM changelog").fetchone()[0], before - 249)
        self.assertEqual(db.last_change_id(c), before)       # the live marker never moves backwards
        c.close()

    def test_prune_is_a_noop_when_disabled_or_under_the_limit(self):
        c = db.connect(db.LIVE)
        self._fill(c, 50)
        self.assertEqual(db.prune_changelog(c, 0), 0)
        self.assertEqual(db.prune_changelog(c, 100), 0)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM changelog").fetchone()[0], 50)
        c.close()

    def test_seed_reset_removes_wal_sidecars(self):
        for suffix in ("-wal", "-shm"):
            with open(db.LIVE + suffix, "wb") as handle:
                handle.write(b"stale")
        with mock.patch.object(appcode, "write_source"), mock.patch.object(seed, "demo_orders", create=True):
            try:
                seed.reset()
            finally:
                db.clock.offset = 0
        c = db.connect(db.LIVE)
        self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertGreater(c.execute("SELECT COUNT(*) FROM inventory").fetchone()[0], 1000)
        c.close()


class SessionEvictionTests(unittest.TestCase):
    def setUp(self):
        agent.SESSIONS.clear()

    def tearDown(self):
        agent.SESSIONS.clear()

    def _add(self, phase, age):
        s = agent.Session("p")
        s.phase, s.created = phase, time.time() - age
        agent.SESSIONS[s.id] = s
        return s

    def test_under_limit_nothing_is_evicted(self):
        self._add("error", 1)
        self.assertEqual(agent.evict_sessions(5), 0)

    def test_in_flight_sessions_are_never_evicted(self):
        running = [self._add(p, 100 - i) for i, p in enumerate(("planning", "awaiting_approval", "applying"))]
        self.assertEqual(agent.evict_sessions(0), 0)
        self.assertTrue(all(s.id in agent.SESSIONS for s in running))

    def test_finished_sessions_go_before_applied_and_oldest_first(self):
        applied_old = self._add("applied", 500)
        err_new, err_old = self._add("error", 10), self._add("discarded", 300)
        self.assertEqual(agent.evict_sessions(2), 1)
        self.assertNotIn(err_old.id, agent.SESSIONS)
        self.assertIn(err_new.id, agent.SESSIONS)
        self.assertIn(applied_old.id, agent.SESSIONS)
        self.assertEqual(agent.evict_sessions(1), 1)
        self.assertNotIn(err_new.id, agent.SESSIONS)          # error evicted before the (older) applied one

    def test_start_keeps_the_map_bounded(self):
        with mock.patch.object(agent, "MAX_SESSIONS", 3), mock.patch.object(agent, "_run"), \
                mock.patch.object(agent, "_record_audit"):
            for _ in range(10):
                agent.start("x", background=False)
                for s in agent.SESSIONS.values():
                    s.phase = "discarded"
        self.assertLessEqual(len(agent.SESSIONS), 3)


class WarmLoopTests(IsolatedDB):
    def test_warm_tick_does_not_hold_the_global_lock(self):
        held = []
        real = db.clone

        def spy(conn, dest):
            # RLock: acquiring from another thread tells us whether warm_tick holds it
            got = []
            t = threading.Thread(target=lambda: got.append(db.LOCK.acquire(blocking=False)) or (db.LOCK.release() if got[0] else None))
            t.start(); t.join()
            held.append(not got[0])
            return real(conn, dest)

        ctx = harness.make_context()
        with mock.patch.object(db, "clone", spy):
            Maintenance(ctx).warm_tick()
        self.assertEqual(held, [False])
        self.assertIsNotNone(ctx.warm["ms"])

    def test_loop_survives_failures_and_logs_once_per_streak(self):
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            if calls["n"] >= 4:
                raise SystemExit              # leave the infinite loop
            raise RuntimeError("db gone")

        maintenance = Maintenance(harness.make_context())
        with mock.patch.object(maintenance, "warm_tick", boom), \
                self.assertLogs("timetravel.http", level="ERROR") as logs, \
                self.assertRaises(SystemExit):
            maintenance.run_forever(sleep=lambda seconds: None)
        self.assertEqual(calls["n"], 4)
        self.assertEqual(len(logs.records), 1)


if __name__ == "__main__":
    unittest.main()

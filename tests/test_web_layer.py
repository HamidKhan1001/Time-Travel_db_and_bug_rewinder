"""The timetravel.web package, module by module: security (no sockets), router, request parsing, static files,
the handler pipeline and context isolation."""
import http.client
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness

from timetravel import agent, appcode, db
from timetravel.ratelimit import RateLimiter
from timetravel.web import app as web_app
from timetravel.web import static
from timetravel.web.context import AppContext
from timetravel.web.http import (
    BadHost,
    BadRequest,
    HttpError,
    NotFound,
    PayloadTooLarge,
    RateLimited,
    Request,
    Response,
    Unauthorized,
)
from timetravel.web.maintenance import Maintenance
from timetravel.web.router import Router
from timetravel.web.security import Security


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


def security(**overrides):
    cfg = harness.default_settings(**overrides)
    clock = Clock()
    limiters = {"read": RateLimiter(60, 3, clock=clock), "write": RateLimiter(60, 2, clock=clock),
                "auth": RateLimiter(60, 2, clock=clock)}
    return Security(cfg, limiters), clock


# ---------------------------------------------------------------------------------------------- security
class SecurityUnitTests(unittest.TestCase):
    def test_host_check_is_automatic_on_loopback_and_off_when_public(self):
        sec, _ = security()
        self.assertTrue(sec.host_ok({"Host": "localhost:8000"}))
        self.assertTrue(sec.host_ok({"Host": "127.0.0.1"}))
        self.assertTrue(sec.host_ok({"Host": "[::1]:8000"}))
        self.assertFalse(sec.host_ok({"Host": "evil.example"}))
        self.assertFalse(sec.host_ok({}))
        public, _ = security(host="0.0.0.0")
        self.assertTrue(public.host_ok({"Host": "anything.example"}))
        listed, _ = security(host="0.0.0.0", allowed_hosts=("app.example.com",))
        self.assertTrue(listed.host_ok({"Host": "APP.example.com:443"}))
        self.assertFalse(listed.host_ok({"Host": "other.example.com"}))

    def test_client_ip_ignores_forwarded_for_unless_trusted_and_uses_the_rightmost_entry(self):
        plain, _ = security()
        self.assertEqual(plain.client_ip({"X-Forwarded-For": "1.1.1.1"}, "10.0.0.9"), "10.0.0.9")
        trusted, _ = security(trust_proxy=True)
        self.assertEqual(trusted.client_ip({"X-Forwarded-For": "6.6.6.6, 7.7.7.7"}, "10.0.0.9"), "7.7.7.7")
        self.assertEqual(trusted.client_ip({}, "10.0.0.9"), "10.0.0.9")

    def test_origin_rules(self):
        sec, _ = security()
        self.assertTrue(sec.origin_allowed("http://localhost:5173"))
        self.assertFalse(sec.origin_allowed("https://evil.example"))
        self.assertTrue(sec.same_origin("https://app.example.com", {"Host": "app.example.com"}))
        self.assertFalse(sec.same_origin("https://evil.example", {"Host": "app.example.com"}))
        self.assertTrue(sec.check_post_origin({}))                                    # no Origin header: not a browser
        self.assertFalse(sec.check_post_origin({"Origin": "https://evil.example", "Host": "localhost"}))
        listed, _ = security(allowed_origins=("https://ui.example",))
        self.assertTrue(listed.origin_allowed("https://ui.example/"))
        self.assertFalse(listed.origin_allowed("http://localhost:5173"))

    def test_cors_headers_only_for_allowed_origins(self):
        sec, _ = security()
        self.assertEqual(sec.cors_headers({"Origin": "https://evil.example"}), [])
        self.assertEqual(sec.cors_headers({}), [])
        names = [n for n, _ in sec.cors_headers({"Origin": "http://localhost:5173"})]
        self.assertIn("Access-Control-Allow-Origin", names)
        self.assertIn("Access-Control-Expose-Headers", names)

    def test_response_headers_include_csp_unless_disabled(self):
        sec, _ = security()
        names = [n for n, _ in sec.response_headers()]
        self.assertEqual(names[:2], ["X-Content-Type-Options", "X-Frame-Options"])
        self.assertIn("Content-Security-Policy", names)
        off, _ = security(csp="")
        self.assertNotIn("Content-Security-Policy", [n for n, _ in off.response_headers()])

    def test_admit_rejects_in_order_host_then_auth_then_rate(self):
        sec, clock = security(api_token="tok")
        with self.assertRaises(BadHost):
            sec.admit("GET", "/api/state", {"Host": "evil"}, "1.1.1.1")
        with self.assertRaises(Unauthorized) as ctx:
            sec.admit("GET", "/api/state", {"Host": "localhost"}, "1.1.1.1")
        self.assertEqual(ctx.exception.headers, {"WWW-Authenticate": "Bearer"})
        ok = {"Host": "localhost", "Authorization": "Bearer tok"}
        for remaining in (2, 1, 0):
            self.assertEqual(sec.admit("GET", "/api/state", ok, "2.2.2.2")["X-RateLimit-Remaining"], remaining)
        with self.assertRaises(RateLimited) as limited:
            sec.admit("GET", "/api/state", ok, "2.2.2.2")
        self.assertEqual(limited.exception.headers["Retry-After"], 1)
        clock.t += 1
        sec.admit("GET", "/api/state", ok, "2.2.2.2")                                 # refilled

    def test_health_options_and_static_paths_are_not_charged(self):
        sec, _ = security(api_token="tok")
        host = {"Host": "localhost"}
        for _ in range(10):
            self.assertEqual(sec.admit("GET", "/api/health", host, "1.1.1.1"), {})
            self.assertEqual(sec.admit("GET", "/app/index.html", host, "1.1.1.1"), {})
            self.assertEqual(sec.admit("OPTIONS", "/api/state", host, "1.1.1.1"), {})

    def test_failed_auth_lockout_then_recovers_and_does_not_block_a_valid_token(self):
        sec, clock = security(api_token="tok")
        bad = {"Host": "localhost", "Authorization": "Bearer nope"}
        for _ in range(2):
            with self.assertRaises(Unauthorized):
                sec.admit("GET", "/api/state", bad, "3.3.3.3")
        with self.assertRaises(RateLimited):
            sec.admit("GET", "/api/state", bad, "3.3.3.3")
        sec.admit("GET", "/api/state", {"Host": "localhost", "Authorization": "Bearer tok"}, "3.3.3.3")
        clock.t += 60
        with self.assertRaises(Unauthorized):
            sec.admit("GET", "/api/state", bad, "3.3.3.3")

    def test_disabled_rate_limiting_still_authenticates(self):
        sec, _ = security(api_token="tok", rate_limit_enabled=False)
        for _ in range(20):
            with self.assertRaises(Unauthorized):
                sec.admit("GET", "/api/state", {"Host": "localhost"}, "1.1.1.1")


# ---------------------------------------------------------------------------------------------- router + request
class RouterTests(unittest.TestCase):
    def test_matches_in_order_with_params_and_method(self):
        r = Router()
        r.get("/api/audit/summary", "summary")
        r.get("/api/audit/{id}", "entry")
        r.post("/api/audit/{id}", "post")
        r.get("/app/{path:path}", "static")
        self.assertEqual(r.match("GET", "/api/audit/summary")[0].handler, "summary")        # static wins over {id}
        route, params = r.match("GET", "/api/audit/INC-1")
        self.assertEqual((route.handler, params), ("entry", {"id": "INC-1"}))
        self.assertEqual(r.match("POST", "/api/audit/INC-1")[0].handler, "post")
        self.assertEqual(r.match("GET", "/app/assets/a/b.js")[1], {"path": "assets/a/b.js"})
        self.assertIsNone(r.match("DELETE", "/api/audit/INC-1"))
        self.assertIsNone(r.match("GET", "/api/audit/a/b"))                                  # {id} is one segment
        self.assertIsNone(r.match("GET", "/api/audit"))

    def test_openapi_path_uses_plain_braces(self):
        r = Router()
        r.get("/app/{path:path}", None)
        self.assertEqual(r.routes[0].openapi_path, "/app/{path}")

    def test_regex_metacharacters_in_patterns_are_literal(self):
        r = Router()
        r.get("/a.b/{id}", "x")
        self.assertIsNotNone(r.match("GET", "/a.b/1"))
        self.assertIsNone(r.match("GET", "/aXb/1"))


class RequestBodyTests(unittest.TestCase):
    def req(self, raw, length=None, limit=1024):
        ctx = harness.make_context(max_body_bytes=limit)
        headers = {"Content-Length": str(len(raw) if length is None else length)}
        return Request(ctx=ctx, method="POST", path="/x", query={"a": ["1"]}, headers=headers, client_ip="1.1.1.1",
                       request_id="r", read_body=lambda n: raw[:n])

    def test_valid_object_is_parsed_once(self):
        r = self.req(b'{"a": 1}')
        self.assertEqual(r.json(), {"a": 1})
        self.assertIs(r.json(), r.json())

    def test_empty_body_is_an_empty_object(self):
        self.assertEqual(self.req(b"").json(), {})

    def test_rejects_bad_json_non_objects_bad_lengths_and_oversize(self):
        for raw in (b"{oops", b"[1]", b'"s"', b"\xff\xfe"):
            with self.assertRaises(BadRequest, msg=raw):
                self.req(raw).json()
        for length in ("-1", "abc", "1.5"):
            r = self.req(b"{}")
            r.headers = {"Content-Length": length}
            with self.assertRaises(BadRequest, msg=length):
                r.json()
        with self.assertRaises(PayloadTooLarge):
            self.req(b"x" * 2000, limit=1000).json()

    def test_query_args_have_defaults(self):
        r = self.req(b"{}")
        self.assertEqual((r.arg("a"), r.arg("missing"), r.arg("missing", "d")), ("1", "", "d"))


# ---------------------------------------------------------------------------------------------- static files
class StaticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dist = os.path.join(self.tmp.name, "dist")
        os.makedirs(os.path.join(self.dist, "assets"))
        with open(os.path.join(self.dist, "index.html"), "w") as f:
            f.write("<html>shell</html>")
        with open(os.path.join(self.dist, "assets", "app.js"), "w") as f:
            f.write("console.log(1)")
        with open(os.path.join(self.tmp.name, "secret.txt"), "w") as f:
            f.write("top secret")

    def test_serves_files_with_the_right_type_and_falls_back_to_the_shell(self):
        js = static.serve_app("assets/app.js", self.dist)
        self.assertEqual((js.status, js.content_type, js.body), (200, "application/javascript; charset=utf-8", b"console.log(1)"))
        for route in ("", "console", "audit-log/x"):
            r = static.serve_app(route, self.dist)
            self.assertEqual((r.status, r.body), (200, b"<html>shell</html>"), route)

    def test_a_missing_asset_is_404_not_the_shell(self):
        self.assertEqual(static.serve_app("assets/nope.js", self.dist).status, 404)

    def test_path_traversal_never_leaves_the_app_directory(self):
        for attempt in ("../secret.txt", "assets/../../secret.txt", "/../secret.txt", "....//secret.txt"):
            r = static.serve_app(attempt, self.dist)
            self.assertNotEqual(r.body, b"top secret", attempt)

    def test_symlink_escape_is_refused(self):
        os.symlink(os.path.join(self.tmp.name, "secret.txt"), os.path.join(self.dist, "assets", "leak.txt"))
        self.assertNotEqual(static.serve_app("assets/leak.txt", self.dist).body, b"top secret")

    def test_unbuilt_app_explains_how_to_build_it(self):
        r = static.serve_app("", os.path.join(self.tmp.name, "empty"))
        self.assertEqual(r.status, 404)
        self.assertIn("npm run build", r.body["error"])


# ---------------------------------------------------------------------------------------------- pipeline
class PipelineTests(unittest.TestCase):
    def setUp(self):
        db.clock.offset = 0
        self.tmp = tempfile.TemporaryDirectory()
        self.original = (db.LIVE, db.DATA, db.connect)
        db.LIVE = os.path.join(self.tmp.name, "live.db")
        db.DATA = self.tmp.name
        orig = self.original[2]
        db.connect = lambda path=None: orig(db.LIVE if path is None else path)
        c = db.connect(db.LIVE)
        db.create_schema(c)
        c.close()
        appcode.reload()
        self.running = harness.start_server()

    def tearDown(self):
        self.running.stop()
        agent.SESSIONS.clear()
        db.LIVE, db.DATA, db.connect = self.original
        self.tmp.cleanup()

    def call(self, method, path, body=None, headers=None, port=None):
        c = http.client.HTTPConnection("127.0.0.1", port or self.running.port, timeout=3)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, (json.loads(raw) if raw[:1] == b"{" else None), r

    def test_unknown_routes_keep_their_historical_messages(self):
        self.assertEqual(self.call("GET", "/api/nope")[1]["error"], "not found")
        self.assertEqual(self.call("POST", "/api/nope", body="{}")[1]["error"], "unknown route /api/nope")

    def test_a_get_only_path_does_not_answer_post_and_vice_versa(self):
        self.assertEqual(self.call("POST", "/api/state", body="{}")[0], 404)
        self.assertEqual(self.call("GET", "/api/rewind")[0], 404)

    def test_body_and_origin_are_checked_before_routing_even_for_unknown_paths(self):
        self.assertEqual(self.call("POST", "/api/nope", body="{bad")[0], 400)
        self.assertEqual(self.call("POST", "/api/nope", body="{}", headers={"Origin": "https://evil.example"})[0], 403)

    def test_a_missing_field_is_400_with_the_field_name(self):
        status, body, _ = self.call("POST", "/api/orders", body="{}")
        self.assertEqual((status, body["code"], body["error"]), (400, "BAD_REQUEST", "missing field 'customer_id'"))

    def test_unexpected_error_in_a_get_is_500_and_in_a_post_is_a_400_with_the_message(self):
        with mock.patch("timetravel.web.routes.state.build_state", side_effect=RuntimeError("boom")):
            self.assertEqual(self.call("GET", "/api/state")[1]["error"], "internal error")
        with mock.patch("timetravel.web.routes.orders._call_handler", side_effect=ValueError("sku is required")):
            status, body, _ = self.call("POST", "/api/orders", body='{"x":1}')
        self.assertEqual((status, body["error"]), (400, "sku is required"))

    def test_every_response_has_a_request_id_and_the_access_log_records_it(self):
        with self.assertLogs("timetravel.http", level="INFO") as logs:
            _, _, r = self.call("GET", "/", headers={"X-Request-Id": "trace-9"})
        self.assertEqual((r.status, r.getheader("X-Request-Id")), (302, "trace-9"))
        self.assertTrue(any("request_id=trace-9" in line and "status=302" in line for line in logs.output))

    def test_two_servers_with_different_settings_do_not_share_state(self):
        other = harness.start_server(demo_routes=False, rate_read_burst=1, rate_read_per_minute=1)
        try:
            self.assertNotEqual(self.call("POST", "/api/demo/orders", body="{}")[0], 404)        # enabled here ...
            self.assertEqual(self.call("POST", "/api/demo/orders", body="{}", port=other.port)[0], 404)   # ... hidden there
            self.assertEqual(self.call("GET", "/api/state", port=other.port)[0], 200)
            self.assertEqual(self.call("GET", "/api/state", port=other.port)[0], 429)
            self.assertEqual(self.call("GET", "/api/state")[0], 200)                 # the first server is unaffected
        finally:
            other.stop()

    def test_dashboard_skus_come_from_configuration(self):
        c = db.connect()
        for sku in ("X-1", "X-2"):
            c.execute("INSERT INTO inventory VALUES(?,?,?,?)", (sku, sku, 5, 100))
        c.close()
        self.running.ctx.reconfigure(dashboard_skus=("X-2",))
        self.assertEqual([s["sku"] for s in self.call("GET", "/api/state")[1]["inventory"]["sample"]], ["X-2"])

    def test_a_stream_that_fails_midway_closes_cleanly_and_frees_its_slot(self):
        """After the headers are sent there is no way to report an error: the connection must just end, and the
        stream slot must come back (otherwise 32 failures would lock everyone out of live updates)."""
        agent.start("restore inventory to before the crash", background=False)
        sid = next(iter(agent.SESSIONS))

        def broken_frames(*args, **kwargs):
            yield "id: 1\nevent: x\ndata: {}\n\n"
            raise RuntimeError("generator blew up")

        slots = self.running.ctx.sse_slots
        with mock.patch("timetravel.web.streaming.sse.iter_sse_frames", broken_frames), \
                self.assertLogs("timetravel.http", level="ERROR") as logs:
            c = http.client.HTTPConnection("127.0.0.1", self.running.port, timeout=3)
            c.request("GET", f"/api/session/{sid}/events")
            r = c.getresponse()
            body = r.read()
            c.close()
        self.assertEqual(r.status, 200)
        self.assertIn(b"retry: 3000", body)
        self.assertNotIn(b"HTTP/1", body)                                    # no second response glued onto the stream
        self.assertTrue(any("event stream failed" in line for line in logs.output))
        for _ in range(self.running.ctx.cfg.max_sse_streams):               # every slot is available again
            self.assertTrue(slots.acquire(blocking=False))

    def test_http_error_defaults_and_overrides(self):
        self.assertEqual((NotFound("x").status, NotFound("x").code), (404, "NOT_FOUND"))
        e = HttpError("m", 418, "TEAPOT", {"X": 1})
        self.assertEqual((e.status, e.code, e.headers), (418, "TEAPOT", {"X": 1}))
        self.assertEqual(Response().status, 200)

    def test_context_reconfigure_is_visible_to_security(self):
        ctx = AppContext.create(harness.default_settings())
        ctx.reconfigure(api_token="abc")
        self.assertTrue(ctx.security.authorized({"Authorization": "Bearer abc"}))
        self.assertFalse(ctx.security.authorized({}))


# ---------------------------------------------------------------------------------------------- startup + upkeep
class StartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original = (db.LIVE, db.DATA, db.connect)
        self.addCleanup(lambda: setattr(db, "LIVE", self.original[0]) or setattr(db, "DATA", self.original[1])
                        or setattr(db, "connect", self.original[2]))
        db.LIVE = os.path.join(self.tmp.name, "live.db")
        db.DATA = self.tmp.name
        orig = self.original[2]
        db.connect = lambda path=None: orig(db.LIVE if path is None else path)

    def test_bootstrap_seeds_only_when_there_is_no_database_and_always_indexes(self):
        ctx = harness.make_context()

        def fake_seed():
            conn = db.connect()
            db.create_schema(conn)
            conn.execute("DROP INDEX ix_changelog_ts")            # simulate a database from before the index existed
            conn.close()

        with mock.patch.object(web_app.seed, "reset", side_effect=fake_seed) as reset, \
                mock.patch.object(web_app.appcode, "reload") as reload_:
            web_app.bootstrap(ctx)
            web_app.bootstrap(ctx)
        self.assertEqual(reset.call_count, 1)                      # second start finds the database
        self.assertEqual(reload_.call_count, 2)
        conn = db.connect()
        self.assertTrue(conn.execute("SELECT 1 FROM sqlite_master WHERE name='ix_changelog_ts'").fetchone())
        conn.close()

    def test_exposure_warnings(self):
        with self.assertLogs("timetravel.http", level="WARNING") as logs:
            web_app.warn_about_exposure(harness.default_settings(host="0.0.0.0"))
        text = " ".join(logs.output)
        self.assertIn("no TT_API_TOKEN", text)
        self.assertIn("demo routes", text)
        with self.assertNoLogs("timetravel.http", level="WARNING"):
            web_app.warn_about_exposure(harness.default_settings())                               # loopback: quiet
            web_app.warn_about_exposure(harness.default_settings(host="0.0.0.0", api_token="t", demo_routes=False))

    def test_main_wires_everything_and_serves(self):
        server = mock.Mock()
        with mock.patch.object(web_app.config, "load", return_value=harness.default_settings(log_level="WARNING")), \
                mock.patch.object(web_app, "bootstrap") as bootstrap, \
                mock.patch.object(web_app.Maintenance, "start") as start, \
                mock.patch.object(web_app, "make_server", return_value=server) as make, \
                mock.patch("builtins.print"):
            web_app.main()
        bootstrap.assert_called_once()
        start.assert_called_once()
        make.assert_called_once()
        server.serve_forever.assert_called_once()

    def test_make_server_binds_the_requested_port(self):
        server = web_app.make_server(harness.make_context(), "127.0.0.1", 0)
        try:
            self.assertGreater(server.server_address[1], 0)
            self.assertEqual(server.RequestHandlerClass.timeout, harness.default_settings().request_timeout)
        finally:
            server.server_close()

    def test_prune_tick_trims_the_changelog_to_the_configured_size(self):
        conn = db.connect()
        db.create_schema(conn)
        conn.execute("BEGIN")
        conn.executemany("INSERT INTO changelog(ts,tbl,op,pk,old,new) VALUES(?,?,?,?,?,?)",
                         [(float(i), "inventory", "U", i, "{}", "{}") for i in range(50)])
        conn.execute("COMMIT")
        conn.close()
        self.assertEqual(Maintenance(harness.make_context(changelog_max_rows=10)).prune_tick(), 40)
        self.assertEqual(Maintenance(harness.make_context(changelog_max_rows=0)).prune_tick(), 0)    # 0 keeps everything

    def test_start_runs_the_loop_on_a_daemon_thread(self):
        with mock.patch.object(Maintenance, "run_forever") as loop:
            thread = Maintenance(harness.make_context()).start()
            thread.join(timeout=2)
        loop.assert_called_once()
        self.assertTrue(thread.daemon)


if __name__ == "__main__":
    unittest.main()

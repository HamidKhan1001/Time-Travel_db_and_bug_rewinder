"""Configuration, rate limiting, security headers, origin/host checks and the error envelope."""
import http.client
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness

from timetravel import agent, appcode, config, db
from timetravel.ratelimit import RateLimiter
from timetravel.web.context import AppContext
from timetravel.web.routes import orders as orders_routes
from timetravel.web.security import Security


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# --------------------------------------------------------------------------- configuration
class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        s = config.load({})
        self.assertEqual((s.host, s.port, s.max_body_bytes, s.rate_limit_enabled), ("127.0.0.1", 8000, 1048576, True))
        self.assertEqual((s.rate_read_per_minute, s.rate_write_per_minute), (600, 60))
        self.assertEqual(s.demo_crash_sku, "APX-0007")
        self.assertTrue(s.csp.startswith("default-src 'self'"))

    def test_overrides_are_parsed_and_trimmed(self):
        s = config.load({"PORT": " 9000 ", "TT_ALLOWED_ORIGINS": "https://a.example/, https://b.example",
                         "TT_ALLOWED_HOSTS": "App.Example.com", "TT_TRUST_PROXY": "yes", "TT_RATE_LIMIT": "off",
                         "TT_DATA_DIR": "/tmp/tt-data", "TT_DEMO_SKU": "APX-0042", "TT_DEMO_ROUTES": "0"})
        self.assertEqual(s.port, 9000)
        self.assertEqual(s.allowed_origins, ("https://a.example", "https://b.example"))
        self.assertEqual(s.allowed_hosts, ("app.example.com",))
        self.assertTrue(s.trust_proxy)
        self.assertFalse(s.rate_limit_enabled)
        self.assertFalse(s.demo_routes)
        self.assertEqual((s.demo_crash_sku, s.data_dir), ("APX-0042", os.path.abspath("/tmp/tt-data")))

    def test_invalid_values_fail_fast_and_name_the_variable(self):
        for env, name in [({"PORT": "abc"}, "PORT"), ({"PORT": "70000"}, "PORT"),
                          ({"TT_MAX_BODY_BYTES": "0"}, "TT_MAX_BODY_BYTES"), ({"TT_RATE_LIMIT": "maybe"}, "TT_RATE_LIMIT"),
                          ({"TT_REQUEST_TIMEOUT": "-1"}, "TT_REQUEST_TIMEOUT"), ({"TT_PACE": "x"}, "TT_PACE")]:
            with self.assertRaises(config.ConfigError, msg=str(env)) as ctx:
                config.load(env)
            self.assertIn(name, str(ctx.exception))

    def test_empty_csp_disables_the_header(self):
        self.assertEqual(config.load({"TT_CSP": ""}).csp, "")

    def test_data_dir_follows_the_environment(self):
        self.assertEqual(config.load({"TT_DATA_DIR": "/var/tt"}).data_dir, "/var/tt")
        self.assertTrue(db.DATA)


# --------------------------------------------------------------------------- rate limiter
class RateLimiterTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()

    def test_burst_then_refusal_with_accurate_retry_after(self):
        rl = RateLimiter(60, 3, clock=self.clock)                 # 1 token per second
        self.assertEqual([rl.check("a").allowed for _ in range(3)], [True, True, True])
        d = rl.check("a")
        self.assertFalse(d.allowed)
        self.assertEqual((d.retry_after, d.remaining, d.limit), (1, 0, 3))

    def test_tokens_refill_over_time_but_never_past_burst(self):
        rl = RateLimiter(60, 2, clock=self.clock)
        rl.check("a"); rl.check("a")
        self.assertFalse(rl.check("a").allowed)
        self.clock.t += 1.0
        self.assertTrue(rl.check("a").allowed)
        self.clock.t += 3600
        self.assertEqual(rl.check("a").remaining, 1)              # capped at burst (2), minus this request

    def test_keys_are_independent(self):
        rl = RateLimiter(60, 1, clock=self.clock)
        self.assertTrue(rl.check("a").allowed)
        self.assertFalse(rl.check("a").allowed)
        self.assertTrue(rl.check("b").allowed)

    def test_zero_rate_disables_the_limiter(self):
        rl = RateLimiter(0, 5, clock=self.clock)
        self.assertTrue(all(rl.check("a").allowed for _ in range(1000)))

    def test_blocked_peeks_without_spending(self):
        rl = RateLimiter(60, 1, clock=self.clock)
        self.assertTrue(rl.blocked("a").allowed)
        self.assertTrue(rl.blocked("a").allowed)                  # peeking twice costs nothing
        rl.check("a")
        d = rl.blocked("a")
        self.assertFalse(d.allowed)
        self.assertGreaterEqual(d.retry_after, 1)

    def test_memory_is_bounded(self):
        rl = RateLimiter(60, 5, clock=self.clock, max_keys=50)
        for i in range(500):
            self.clock.t += 0.01
            rl.check(f"ip-{i}")
        self.assertLessEqual(len(rl), 50)

    def test_thread_safety_never_exceeds_burst(self):
        rl = RateLimiter(1, 100, clock=self.clock)                # clock frozen: no refill
        granted = []
        def worker():
            granted.extend(rl.check("a").allowed for _ in range(50))
        threads = [threading.Thread(target=worker) for _ in range(8)]
        [t.start() for t in threads]; [t.join() for t in threads]
        self.assertEqual(sum(granted), 100)


# --------------------------------------------------------------------------- HTTP behaviour
class HttpSecurityBase(unittest.TestCase):
    # (per minute, burst) for read / write / failed-auth buckets; roomy by default, tightened by the tests about limits
    LIMITS = {"read": (6000, 1000), "write": (6000, 1000), "auth": (6000, 1000)}

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
        self.clock = FakeClock()
        cfg = harness.default_settings()
        limiters = {name: RateLimiter(rate, burst, clock=self.clock) for name, (rate, burst) in self.LIMITS.items()}
        self.ctx = AppContext.create(cfg, Security(cfg, limiters))
        self.running = harness.start_server(self.ctx)
        self.port = self.running.port

    def tearDown(self):
        self.running.stop()
        agent.SESSIONS.clear()
        db.LIVE, db.DATA, db.connect = self.original
        self.tmp.cleanup()

    def use_cfg(self, **changes):
        self.ctx.reconfigure(**changes)

    def call(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = None
        return r.status, payload, r


class RateLimitHttpTests(HttpSecurityBase):
    LIMITS = {"read": (60, 5), "write": (60, 2), "auth": (60, 3)}

    def test_reads_are_limited_with_429_retry_after_and_headers(self):
        for i in range(5):
            status, _, r = self.call("GET", "/api/state")
            self.assertEqual(status, 200)
            self.assertEqual(r.getheader("X-RateLimit-Limit"), "5")
            self.assertEqual(r.getheader("X-RateLimit-Remaining"), str(4 - i))
        status, body, r = self.call("GET", "/api/state")
        self.assertEqual(status, 429)
        self.assertEqual(body["code"], "RATE_LIMITED")
        self.assertTrue(body["request_id"])
        self.assertEqual(r.getheader("Retry-After"), "1")
        self.clock.t += 1.0
        self.assertEqual(self.call("GET", "/api/state")[0], 200)

    def test_writes_have_their_own_stricter_bucket(self):
        for _ in range(2):
            self.assertNotEqual(self.call("POST", "/api/demo/orders", body="{}")[0], 429)
        status, body, _ = self.call("POST", "/api/demo/orders", body="{}")
        self.assertEqual((status, body["code"]), (429, "RATE_LIMITED"))
        self.assertEqual(self.call("GET", "/api/state")[0], 200)     # reads are unaffected

    def test_health_and_static_are_never_limited(self):
        for _ in range(30):
            self.assertEqual(self.call("GET", "/api/health")[0], 200)
        for _ in range(30):
            self.assertIn(self.call("GET", "/app/")[0], (200, 404))  # 404 only when the UI is not built

    def test_disabled_flag_turns_limiting_off(self):
        self.use_cfg(rate_limit_enabled=False)
        self.assertTrue(all(self.call("GET", "/api/state")[0] == 200 for _ in range(12)))

    def test_forwarded_for_is_ignored_unless_the_proxy_is_trusted(self):
        for i in range(5):
            self.call("GET", "/api/state", headers={"X-Forwarded-For": f"9.9.9.{i}"})
        self.assertEqual(self.call("GET", "/api/state", headers={"X-Forwarded-For": "1.2.3.4"})[0], 429)

    def test_trusted_proxy_uses_the_rightmost_entry_so_spoofing_the_left_does_nothing(self):
        self.use_cfg(trust_proxy=True)
        for i in range(5):                                          # same real client, spoofed left-hand values
            self.call("GET", "/api/state", headers={"X-Forwarded-For": f"6.6.6.{i}, 10.0.0.1"})
        self.assertEqual(self.call("GET", "/api/state", headers={"X-Forwarded-For": "7.7.7.7, 10.0.0.1"})[0], 429)
        self.assertEqual(self.call("GET", "/api/state", headers={"X-Forwarded-For": "7.7.7.7, 10.0.0.2"})[0], 200)


class AuthHttpTests(HttpSecurityBase):
    LIMITS = {"read": (60, 5), "write": (60, 2), "auth": (60, 3)}

    def setUp(self):
        super().setUp()
        self.use_cfg(api_token="s3cret-token")

    def test_missing_token_is_401_with_challenge_and_code(self):
        status, body, r = self.call("GET", "/api/state")
        self.assertEqual((status, body["code"]), (401, "UNAUTHORIZED"))
        self.assertEqual(r.getheader("WWW-Authenticate"), "Bearer")

    def test_valid_token_passes_and_health_stays_open(self):
        self.assertEqual(self.call("GET", "/api/state", headers={"Authorization": "Bearer s3cret-token"})[0], 200)
        self.assertEqual(self.call("GET", "/api/health")[0], 200)

    def test_repeated_failures_lock_the_address_out_even_for_correct_guesses_on_the_failing_path(self):
        wrong = {"Authorization": "Bearer nope"}
        self.assertEqual([self.call("GET", "/api/state", headers=wrong)[0] for _ in range(3)], [401, 401, 401])
        status, body, r = self.call("GET", "/api/state", headers=wrong)
        self.assertEqual((status, body["code"]), (429, "RATE_LIMITED"))
        self.assertTrue(r.getheader("Retry-After"))
        # a legitimate client with the real token is not punished for someone else's guesses
        self.assertEqual(self.call("GET", "/api/state", headers={"Authorization": "Bearer s3cret-token"})[0], 200)
        self.clock.t += 60
        self.assertEqual(self.call("GET", "/api/state", headers=wrong)[0], 401)       # lock expires


class HeaderAndOriginTests(HttpSecurityBase):
    def test_security_headers_on_json_redirect_and_errors(self):
        for path in ("/api/health", "/", "/api/nope"):
            _, _, r = self.call("GET", path)
            self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff", path)
            self.assertEqual(r.getheader("X-Frame-Options"), "DENY", path)
            self.assertEqual(r.getheader("Referrer-Policy"), "no-referrer", path)
            self.assertIn("frame-ancestors 'none'", r.getheader("Content-Security-Policy"), path)

    def test_csp_is_configurable_and_can_be_disabled(self):
        self.use_cfg(csp="default-src 'none'")
        self.assertEqual(self.call("GET", "/api/health")[2].getheader("Content-Security-Policy"), "default-src 'none'")
        self.use_cfg(csp="")
        self.assertIsNone(self.call("GET", "/api/health")[2].getheader("Content-Security-Policy"))

    def test_api_responses_are_not_cacheable(self):
        self.assertEqual(self.call("GET", "/api/state")[2].getheader("Cache-Control"), "no-store")

    def test_unexpected_host_header_is_refused_while_bound_to_loopback(self):
        status, body, _ = self.call("GET", "/api/health", headers={"Host": "evil.example.com"})
        self.assertEqual((status, body["code"]), (421, "BAD_HOST"))
        self.assertEqual(self.call("GET", "/api/health", headers={"Host": "localhost:8000"})[0], 200)
        self.assertEqual(self.call("GET", "/api/health", headers={"Host": "[::1]:8000"})[0], 200)

    def test_public_bind_allows_any_host_unless_an_allow_list_is_set(self):
        self.use_cfg(host="0.0.0.0")
        self.assertEqual(self.call("GET", "/api/health", headers={"Host": "app.example.com"})[0], 200)
        self.use_cfg(host="0.0.0.0", allowed_hosts=("app.example.com",))
        self.assertEqual(self.call("GET", "/api/health", headers={"Host": "app.example.com:443"})[0], 200)
        self.assertEqual(self.call("GET", "/api/health", headers={"Host": "other.example.com"})[0], 421)

    def test_cross_origin_post_is_forbidden(self):
        status, body, _ = self.call("POST", "/api/rewind", body="{}", headers={"Origin": "https://evil.example"})
        self.assertEqual((status, body["code"]), (403, "FORBIDDEN_ORIGIN"))

    def test_same_origin_post_works_when_hosted_on_a_real_domain(self):
        """The app served by this very server must be able to POST to it (it used to get 403 off-localhost)."""
        self.use_cfg(host="0.0.0.0")
        status, _, _ = self.call("POST", "/api/demo/orders", body="{}",
                                 headers={"Origin": "https://app.example.com", "Host": "app.example.com"})
        self.assertNotEqual(status, 403)

    def test_origin_allow_list_controls_cors_and_posts(self):
        self.use_cfg(allowed_origins=("https://ui.example",))
        _, _, ok = self.call("GET", "/api/health", headers={"Origin": "https://ui.example"})
        self.assertEqual(ok.getheader("Access-Control-Allow-Origin"), "https://ui.example")
        _, _, no = self.call("GET", "/api/health", headers={"Origin": "http://localhost:5173"})
        self.assertIsNone(no.getheader("Access-Control-Allow-Origin"))
        self.assertNotEqual(self.call("POST", "/api/demo/orders", body="{}", headers={"Origin": "https://ui.example"})[0], 403)

    def test_default_cors_allows_local_dev_servers_only(self):
        _, _, r = self.call("GET", "/api/health", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(r.getheader("Access-Control-Allow-Origin"), "http://localhost:5173")
        _, _, r = self.call("GET", "/api/health", headers={"Origin": "https://evil.example"})
        self.assertIsNone(r.getheader("Access-Control-Allow-Origin"))
        self.assertIn("Retry-After", r.getheader("Access-Control-Expose-Headers") or "Retry-After")


class ErrorEnvelopeTests(HttpSecurityBase):
    def test_every_error_has_error_code_and_request_id(self):
        cases = [("GET", "/api/nope", None, 404, "NOT_FOUND"),
                 ("POST", "/api/nope", "{}", 404, "NOT_FOUND"),
                 ("POST", "/api/rewind", "[1]", 400, "BAD_REQUEST"),
                 ("POST", "/api/session/INC-NOPE00/approve", "{}", 404, "NOT_FOUND"),
                 ("POST", "/api/rewind", "{bad json", 400, "BAD_REQUEST"),
                 ("GET", "/api/session/INC-NOPE00", None, 404, "NOT_FOUND")]
        for method, path, body, status, code in cases:
            got, payload, r = self.call(method, path, body=body)
            self.assertEqual((got, payload["code"]), (status, code), path)
            self.assertTrue(payload["error"])
            self.assertEqual(payload["request_id"], r.getheader("X-Request-Id"))

    def test_payload_too_large_code(self):
        self.use_cfg(max_body_bytes=10)
        status, body, _ = self.call("POST", "/api/rewind", body=json.dumps({"prompt": "x" * 100}))
        self.assertEqual((status, body["code"]), (413, "PAYLOAD_TOO_LARGE"))

    def test_database_failure_is_503_with_retry_after_not_a_client_error(self):
        with mock.patch.object(orders_routes, "_call_handler", side_effect=sqlite3.OperationalError("database is locked")):
            status, body, r = self.call("POST", "/api/orders", body="{}")
        self.assertEqual((status, body["code"], r.getheader("Retry-After")), (503, "DB_BUSY", "2"))
        self.assertNotIn("locked", body["error"])


class DemoRouteTests(HttpSecurityBase):
    def test_demo_routes_can_be_switched_off(self):
        self.use_cfg(demo_routes=False)
        for path in ("/api/demo/reset", "/api/demo/crash", "/api/demo/orders"):
            status, body, _ = self.call("POST", path, body="{}")
            self.assertEqual((status, body["code"]), (404, "NOT_FOUND"), path)

    def test_crash_sku_comes_from_configuration(self):
        self.use_cfg(demo_crash_sku="APX-0042")
        seen = {}
        with mock.patch.object(orders_routes, "_call_handler", side_effect=lambda name, body: seen.update(body) or {"ok": True}):
            self.call("POST", "/api/demo/crash", body="{}")
        self.assertEqual(seen, {"sku": "APX-0042", "stock": 0})


if __name__ == "__main__":
    unittest.main()

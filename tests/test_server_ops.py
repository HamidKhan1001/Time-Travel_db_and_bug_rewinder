"""Health endpoint, request IDs, access log, optional bearer token, and the OpenAPI contract."""
import http.client
import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness

import timetravel
from timetravel import agent, appcode, audit, db
from timetravel.web.routes import build_router

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ServerOpsTests(unittest.TestCase):
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
        self.running = harness.start_server()
        self.ctx = self.running.ctx
        self.port = self.running.port

    def tearDown(self):
        self.running.stop()
        agent.SESSIONS.clear()
        db.LIVE, db.DATA, db.connect = self.original
        self.tmp.cleanup()

    def call(self, method, path, headers=None, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = None
        return response.status, payload, response

    # ------------------------------------------------------------ health / ids / logs
    def test_health_reports_ok_and_version(self):
        status, body, _ = self.call("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual((body["status"], body["database"], body["auth"]), ("ok", "ok", "open"))
        self.assertEqual(body["version"], timetravel.__version__)

    def test_version_matches_pyproject(self):
        with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as handle:
            declared = re.search(r'^version = "([^"]+)"', handle.read(), re.M).group(1)
        self.assertEqual(declared, timetravel.__version__)

    def test_request_id_is_generated_or_echoed_and_unsafe_values_are_replaced(self):
        _, _, response = self.call("GET", "/api/health")
        self.assertRegex(response.getheader("X-Request-Id"), r"^[0-9a-f]{12}$")
        _, _, response = self.call("GET", "/api/health", headers={"X-Request-Id": "trace-42"})
        self.assertEqual(response.getheader("X-Request-Id"), "trace-42")
        _, _, response = self.call("GET", "/api/health", headers={"X-Request-Id": "bad id\twith spaces"})
        self.assertRegex(response.getheader("X-Request-Id"), r"^[0-9a-f]{12}$")

    def test_access_log_has_request_id_status_and_path_without_query(self):
        with self.assertLogs("timetravel.http", level="INFO") as logs:
            self.call("GET", "/api/audit/summary?secret=1", headers={"X-Request-Id": "rid-1"})
        line = logs.output[0]
        self.assertIn("request_id=rid-1", line)
        self.assertIn("path=/api/audit/summary ", line)
        self.assertIn("status=200", line)
        self.assertNotIn("secret", line)

    # ------------------------------------------------------------ token
    def test_token_protects_api_but_not_health(self):
        self.ctx.reconfigure(api_token="s3cret")
        self.assertEqual(self.call("GET", "/api/state")[0], 401)
        self.assertEqual(self.call("GET", "/api/state", headers={"Authorization": "Bearer nope"})[0], 401)
        self.assertEqual(self.call("GET", "/api/state", headers={"Authorization": "Bearer s3cret"})[0], 200)
        self.assertEqual(self.call("POST", "/api/demo/orders", body=b"{}")[0], 401)
        status, body, _ = self.call("GET", "/api/health")
        self.assertEqual((status, body["auth"]), (200, "token"))

    def test_preflight_is_not_blocked_by_the_token(self):
        self.ctx.reconfigure(api_token="s3cret")
        status, _, response = self.call("OPTIONS", "/api/rewind", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(status, 204)
        self.assertIn("Authorization", response.getheader("Access-Control-Allow-Headers"))

    def test_missing_field_is_400_and_unknown_session_or_route_is_404(self):
        status, body, _ = self.call("POST", "/api/orders", body=b"{}")
        self.assertEqual((status, body["error"]), (400, "missing field 'customer_id'"))
        status, body, _ = self.call("POST", "/api/session/INC-ABC123/approve", body=b"{}")
        self.assertEqual((status, body["error"]), (404, "session not found"))
        status, body, _ = self.call("POST", "/api/nope", body=b"{}")
        self.assertEqual((status, body["error"]), (404, "unknown route /api/nope"))

    # ------------------------------------------------------------ OpenAPI contract
    def spec(self):
        with open(os.path.join(ROOT, "docs", "openapi.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def test_every_route_is_documented_and_every_documented_route_exists(self):
        """The router is the source of truth for the code; docs/openapi.json for the contract. They must agree."""
        coded = {(r.method.lower(), r.openapi_path) for r in build_router().routes if r.openapi_path.startswith("/api/")}
        documented = {(method, path) for path, operations in self.spec()["paths"].items() for method in operations}
        self.assertEqual(coded - documented, set(), "routes in the code that the spec does not document")
        self.assertEqual(documented - coded, set(), "routes in the spec that the code does not serve")

    def test_documented_routes_exist_on_the_live_server(self):
        for path, operations in self.spec()["paths"].items():
            url = path.replace("{id}", "INC-ABC123")
            for method in operations:
                if path.endswith("/events"):
                    continue                                   # streaming; covered by test_sse
                status, body, _ = self.call(method.upper(), url, body=b"{}" if method == "post" else None)
                documented = {int(code) for code in operations[method]["responses"]}
                message = str((body or {}).get("error", ""))
                self.assertNotEqual(message, "not found", f"{method} {path} is documented but not routed")
                self.assertFalse(message.startswith("unknown route"), f"{method} {path} is documented but not routed")
                self.assertIn(status, documented | {400}, f"{method} {path} returned undocumented {status}")

    def test_response_bodies_contain_the_documented_required_keys(self):
        schemas = self.spec()["components"]["schemas"]
        conn = db.connect()
        audit.record_event(conn, "INC-AAA111", "recovery_initiated", "started", {"prompt": "x"})
        audit.record_event(conn, "INC-AAA111", "recovery_completed", "completed", {})
        conn.close()
        for path, schema in (("/api/health", "Health"), ("/api/state", "State"),
                             ("/api/audit", "AuditList"), ("/api/audit/summary", "AuditSummary"),
                             ("/api/audit/INC-AAA111", "AuditEntry")):
            status, body, _ = self.call("GET", path)
            self.assertEqual(status, 200, path)
            for key in schemas[schema]["required"]:
                self.assertIn(key, body, f"{path} is missing documented key {key!r}")
        session = agent.Session("contract")
        agent.SESSIONS[session.id] = session
        _, body, _ = self.call("GET", f"/api/session/{session.id}")
        for key in schemas["Session"]["required"]:
            self.assertIn(key, body, f"session JSON is missing documented key {key!r}")
        self.assertIn(body["phase"], schemas["Session"]["properties"]["phase"]["enum"])


if __name__ == "__main__":
    unittest.main()

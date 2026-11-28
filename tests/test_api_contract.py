import http.client
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness

from timetravel import agent, appcode, db
from timetravel.web.http import NotFound


class ApiContractTests(unittest.TestCase):
    def setUp(self):
        db.clock.offset = 0
        self.tmp = tempfile.TemporaryDirectory()
        self.original_live = db.LIVE
        self.original_connect = db.connect
        db.LIVE = os.path.join(self.tmp.name, "live.db")
        db.connect = lambda path=None: self.original_connect(db.LIVE if path is None else path)
        conn = db.connect(db.LIVE)
        db.create_schema(conn)
        conn.execute("INSERT INTO customers(id,name,email) VALUES(1,'Ada','ada@example.com')")
        conn.execute("INSERT INTO inventory(sku,name,stock,price_cents) VALUES('APX-0001','Item',10,100)")
        conn.close()
        appcode.reload()

    def tearDown(self):
        agent.SESSIONS.clear()
        db.connect = self.original_connect
        db.LIVE = self.original_live
        db.clock.offset = 0
        self.tmp.cleanup()

    def test_place_order_response_contract(self):
        response = harness.call_route("POST", "/api/orders", {
            "customer_id": 1,
            "idem_key": "api-contract-key",
            "items": [{"sku": "APX-0001", "qty": 2}],
        })
        self.assertIn("order_id", response)
        self.assertIn("total_cents", response)
        self.assertEqual(response["total_cents"], 200)

    def test_duplicate_order_is_idempotent(self):
        body = {
            "customer_id": 1,
            "idem_key": "api-contract-duplicate",
            "items": [{"sku": "APX-0001", "qty": 1}],
        }
        first = harness.call_route("POST", "/api/orders", body)
        second = harness.call_route("POST", "/api/orders", body)
        self.assertEqual(first["order_id"], second["order_id"])
        self.assertEqual(second["duplicate"], True)

    def test_sync_stock_requires_sku_in_live_handler_contract(self):
        response = harness.call_route("POST", "/api/admin/sync-stock", {"sku": "APX-0001", "stock": 7})
        self.assertEqual(response, {"updated_rows": 1})

    def test_unknown_post_route_raises_not_found_for_the_http_layer_to_map_to_404(self):
        with self.assertRaises(NotFound):
            harness.call_route("POST", "/api/not-a-route", {})

    def test_api_state_shape(self):
        state = harness.api_state()
        for key in ("now", "inventory", "orders", "incident", "order_dots", "patched", "warm"):
            self.assertIn(key, state)
        self.assertIn("skus", state["inventory"])
        self.assertIn("units", state["inventory"])
        self.assertIn("zero", state["inventory"])
        self.assertIn("sample", state["inventory"])

    def test_root_redirects_to_the_react_app(self):
        running = harness.start_server()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", running.port, timeout=2)
            for path in ("/", "/index.html"):
                connection.request("GET", path)
                response = connection.getresponse()
                response.read()
                self.assertEqual((response.status, response.getheader("Location")), (302, "/app/"), path)
            connection.close()
        finally:
            running.stop()

    def test_session_endpoint_exposes_timing_contract(self):
        session = agent.Session("api timing contract")
        agent.SESSIONS[session.id] = session
        running = harness.start_server()
        try:
            response = urllib.request.urlopen(f"{running.url}/api/session/{session.id}", timeout=2)
            payload = json.loads(response.read().decode("utf-8"))
            response.close()
        finally:
            running.stop()
        self.assertIn("timings", payload)
        for value in payload["timings"].values():
            self.assertIsNone(value)


if __name__ == "__main__":
    unittest.main()

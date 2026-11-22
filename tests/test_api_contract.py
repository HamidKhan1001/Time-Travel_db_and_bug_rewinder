import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server
from timetravel import appcode, db


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
        db.connect = self.original_connect
        db.LIVE = self.original_live
        db.clock.offset = 0
        self.tmp.cleanup()

    def test_place_order_response_contract(self):
        response = server.post("/api/orders", {
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
        first = server.post("/api/orders", body)
        second = server.post("/api/orders", body)
        self.assertEqual(first["order_id"], second["order_id"])
        self.assertEqual(second["duplicate"], True)

    def test_sync_stock_requires_sku_in_live_handler_contract(self):
        response = server.post("/api/admin/sync-stock", {"sku": "APX-0001", "stock": 7})
        self.assertEqual(response, {"updated_rows": 1})

    def test_unknown_post_route_returns_key_error_for_http_handler_mapping(self):
        with self.assertRaises(KeyError):
            server.post("/api/not-a-route", {})

    def test_api_state_shape(self):
        state = server.api_state()
        for key in ("now", "inventory", "orders", "incident", "order_dots", "patched", "warm"):
            self.assertIn(key, state)
        self.assertIn("skus", state["inventory"])
        self.assertIn("units", state["inventory"])
        self.assertIn("zero", state["inventory"])
        self.assertIn("sample", state["inventory"])

    def test_js_assets_are_served_from_an_allowlist(self):
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        port = httpd.server_address[1]
        try:
            response = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/js/recovery_data.js", timeout=2)
            self.assertEqual(response.status, 200)
            self.assertTrue(response.headers["Content-Type"].startswith("application/javascript"))
            self.assertIn("RecoveryData", response.read().decode("utf-8"))
            response.close()
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/js/%2e%2e/server.py", timeout=2)
            self.assertEqual(raised.exception.code, 404)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()

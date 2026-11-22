import os
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()

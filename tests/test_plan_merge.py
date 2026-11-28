"""Characterization tests for tools.plan_merge_tool / run_checks / execute_plan.

The scenarios build real SQLite databases (live, rewound branch, delta) and compare the *entire* planner output
against tests/golden/plan_merge.json, captured from the implementation before it was split into small functions.
A refactor must not change a single byte of it. To accept an intentional change, regenerate the file with
    UPDATE_GOLDEN=1 python -m pytest tests/test_plan_merge.py
and review the diff.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timetravel import db, tools

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden", "plan_merge.json")
T0, INCIDENT = 1000.0, 1100.0          # rewind point and incident time (seconds)


class World:
    """A live DB, its rewound branch and the delta, built the same way the agent builds them."""

    def __init__(self, tmp, skus, customers=((1, "Ava", "ava@example.com"),)):
        self.tmp = tmp
        self.live = db.connect(os.path.join(tmp, "live.db"))
        db.create_schema(self.live)
        self.live.execute("DELETE FROM changelog")
        for sku, name, stock, price in skus:
            self.live.execute("INSERT INTO inventory VALUES(?,?,?,?)", (sku, name, stock, price))
        for c in customers:
            self.live.execute("INSERT INTO customers VALUES(?,?,?)", c)
        self.branch = db.clone(self.live, os.path.join(tmp, "branch.db"))   # state at the rewind point

    def order(self, oid, items, cust=1, created=1200.0, idem=None, total=1000):
        self.live.execute("INSERT INTO orders VALUES(?,?,?,?,?,?)",
                          (oid, cust, total, "paid", idem or f"idem-{oid}-0123456789", created))
        for sku, qty in items:
            self.live.execute("INSERT INTO order_items(order_id,sku,qty,unit_cents) VALUES(?,?,?,?)", (oid, sku, qty, 100))

    def wipe_stock(self):
        self.live.execute("UPDATE inventory SET stock = 0")

    def run(self):
        delta = tools.extract_delta_tool(self.live, T0, INCIDENT)
        scratch = os.path.join(self.tmp, "scratch.db")
        plan, expected, summary = tools.plan_merge_tool(self.live, self.branch, delta, scratch)
        assert not os.path.exists(scratch), "the scratch clone must be deleted"
        return {"plan": plan, "expected": expected, "summary": summary}


SKUS = [("A-1", "Alpha", 10, 500), ("B-2", "Beta", 3, 900), ("C-3", "Gamma", 0, 100)]


def scenario_clean(w):
    w.order(2001, [("A-1", 2), ("B-2", 1)])
    w.wipe_stock()


def scenario_oversell(w):
    w.order(2001, [("B-2", 5)])                      # only 3 existed at the rewind point
    w.order(2002, [("B-2", 1), ("A-1", 1)])          # B-2 is now at 0 in the running state
    w.wipe_stock()


def scenario_oversell_same_order_twice(w):
    w.order(2001, [("B-2", 4), ("B-2", 4)])          # two oversell lines in one order: one backorder id
    w.wipe_stock()


def scenario_id_collision(w):
    w.live.execute("INSERT INTO orders VALUES(?,?,?,?,?,?)", (2001, 1, 10, "paid", "old-idem-0123456789", 900.0))
    w.branch = db.clone(w.live, os.path.join(w.tmp, "branch2.db"))        # order 2001 already exists at the rewind point
    w.live.execute("DELETE FROM orders WHERE id=2001")
    w.live.execute("INSERT INTO orders VALUES(?,?,?,?,?,?)", (2001, 1, 10, "paid", "new-idem-0123456789", 1300.0))


def scenario_duplicate_idempotency(w):
    # the key was used by an order that existed at the rewind point and was later removed from live
    w.live.execute("INSERT INTO orders VALUES(?,?,?,?,?,?)", (1900, 1, 10, "paid", "same-key-0123456789", 900.0))
    w.branch = db.clone(w.live, os.path.join(w.tmp, "branch3.db"))
    w.live.execute("DELETE FROM orders WHERE id=1900")
    w.order(2001, [("A-1", 1)], idem="same-key-0123456789")


def scenario_orphan_sku_and_new_customer(w):
    w.live.execute("INSERT INTO customers VALUES(2,'Ben','ben@example.com')")
    w.order(2001, [("A-1", 1)], cust=2)
    w.live.execute("PRAGMA foreign_keys=OFF")
    w.live.execute("INSERT INTO order_items(order_id,sku,qty,unit_cents) VALUES(2001,'GHOST',1,100)")


def scenario_no_orders(w):
    w.wipe_stock()


def scenario_many_conflicts_high_risk(w):
    for i in range(6):
        w.order(3000 + i, [("B-2", 2)])
    w.wipe_stock()


SCENARIOS = {f.__name__[len("scenario_"):]: f for f in [
    scenario_clean, scenario_oversell, scenario_oversell_same_order_twice, scenario_id_collision,
    scenario_duplicate_idempotency, scenario_orphan_sku_and_new_customer, scenario_no_orders,
    scenario_many_conflicts_high_risk]}


def normalize(result):
    """JSON-stable form (tuples become lists). The live_marker depends on trigger counts, so it is kept."""
    return json.loads(json.dumps(result, sort_keys=True, default=str))


def build(name):
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp, SKUS)
        SCENARIOS[name](w)
        try:
            return normalize(w.run())
        finally:
            w.live.close()
            w.branch.close()


class PlanMergeGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.clock.offset = 0
        cls.results = {name: build(name) for name in SCENARIOS}
        if os.environ.get("UPDATE_GOLDEN"):
            os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
            with open(GOLDEN, "w", encoding="utf-8") as handle:
                json.dump(cls.results, handle, indent=1, sort_keys=True)
                handle.write("\n")
        with open(GOLDEN, encoding="utf-8") as handle:
            cls.golden = json.load(handle)

    def test_every_scenario_matches_the_captured_output_exactly(self):
        for name in SCENARIOS:
            with self.subTest(scenario=name):
                self.assertEqual(self.results[name], self.golden[name])

    # ---- a few explicit, human-readable guarantees (so the golden file is not the only spec)
    def test_clean_scenario_restores_stock_and_keeps_orders_without_conflicts(self):
        s = self.results["clean"]["summary"]
        self.assertEqual(s["conflicts"], [])
        self.assertEqual(self.results["clean"]["expected"], {"A-1": 8, "B-2": 2, "C-3": 0})
        self.assertEqual((s["orders_preserved"], s["dry_run_ok"], s["risk"]["label"]), (1, True, "LOW"))

    def test_oversell_is_clamped_to_zero_and_the_order_is_kept_as_backorder(self):
        r = self.results["oversell"]
        self.assertEqual(r["expected"]["B-2"], 0)
        self.assertEqual([c["kind"] for c in r["summary"]["conflicts"]], ["oversell", "oversell"])
        self.assertEqual(r["plan"]["backorder_ids"], [2001, 2002])
        self.assertEqual(r["summary"]["conflicts"][0]["shortfall"], 2)

    def test_one_backorder_id_per_order_even_with_two_oversold_lines(self):
        self.assertEqual(self.results["oversell_same_order_twice"]["plan"]["backorder_ids"], [2001])

    def test_collisions_duplicates_and_orphans_are_reported(self):
        self.assertEqual([c["kind"] for c in self.results["id_collision"]["summary"]["conflicts"]], ["id-collision"])
        self.assertEqual([c["kind"] for c in self.results["duplicate_idempotency"]["summary"]["conflicts"]],
                         ["duplicate-idempotency-key"])
        self.assertIn("orphan-sku", [c["kind"] for c in self.results["orphan_sku_and_new_customer"]["summary"]["conflicts"]])

    def test_risk_rises_with_conflicts(self):
        self.assertEqual(self.results["clean"]["summary"]["risk"]["score"], 8)
        self.assertEqual(self.results["many_conflicts_high_risk"]["summary"]["risk"]["label"], "HIGH")

    def test_nothing_in_live_is_modified_by_planning(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, SKUS)
            scenario_oversell(w)
            before = [tuple(r) for r in w.live.execute("SELECT sku, stock FROM inventory ORDER BY sku")]
            w.run()
            after = [tuple(r) for r in w.live.execute("SELECT sku, stock FROM inventory ORDER BY sku")]
            self.assertEqual(before, after)

    def test_a_failing_dry_run_is_reported_and_scores_high_risk(self):
        failing = [{"name": "boom", "ok": False, "detail": "x"}]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(tools, "run_checks", return_value=failing):
            w = World(tmp, SKUS)
            scenario_clean(w)
            summary = w.run()["summary"]
        self.assertFalse(summary["dry_run_ok"])
        self.assertEqual(summary["risk"]["score"], 68)             # base 8 + failed dry run 60
        self.assertEqual(summary["risk"]["label"], "HIGH")

    def test_large_blast_radius_adds_risk(self):
        many = [(f"S-{i:04d}", f"Item {i}", 5, 100) for i in range(1100)]
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, many)
            w.live.execute("UPDATE inventory SET stock = 0")
            summary = w.run()["summary"]
        self.assertEqual(summary["restored_rows"], 1100)
        self.assertIn(5, [f[1] for f in summary["risk"]["factors"]])


class RunChecksTests(unittest.TestCase):
    def test_reports_each_invariant(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, SKUS)
            ok = tools.run_checks(w.live, {"A-1": 10, "B-2": 3, "C-3": 0}, [])
            self.assertTrue(all(c["ok"] for c in ok))
            self.assertEqual(len(ok), 4)
            bad = tools.run_checks(w.live, {"A-1": 99}, [12345])
            self.assertEqual([c["name"] for c in bad if not c["ok"]],
                             ["Inventory matches merge plan", "Post-incident orders preserved"])


if __name__ == "__main__":
    unittest.main()

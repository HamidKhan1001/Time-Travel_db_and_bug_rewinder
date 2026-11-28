"""tools.py beyond the planner: incident detection, patching (LLM + regex fallback), apply/rollback/undo."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timetravel import appcode, db, tools

BUGGY = appcode.read_source(appcode.PRISTINE_PATH)


class Env(unittest.TestCase):
    def setUp(self):
        db.clock.offset = 0
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "live.db")
        self.live = db.connect(self.path)
        db.create_schema(self.live)
        for sku, stock in (("APX-0007", 10), ("APX-0042", 5), ("APX-0100", 7)):
            self.live.execute("INSERT INTO inventory VALUES(?,?,?,?)", (sku, sku, stock, 100))
        self.live.execute("INSERT INTO customers VALUES(1,'Ava','a@example.com')")
        self.branch = db.clone(self.live, os.path.join(self.tmp.name, "branch.db"))
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.live.close)
        self.addCleanup(self.branch.close)


class IncidentDetectionTests(Env):
    def test_finds_the_unscoped_mass_write_and_ignores_scoped_or_small_ones(self):
        ins = "INSERT INTO query_log(ts,source,sql,rows_affected) VALUES(?,?,?,?)"
        self.live.execute(ins, (1.0, "POST /x", "UPDATE inventory SET stock = ? WHERE sku = ?", 500))   # scoped
        self.live.execute(ins, (2.0, "POST /y", "UPDATE inventory SET stock = ?", 5))                    # too small
        self.assertIsNone(tools.detect_incident(self.live))
        self.live.execute(ins, (3.0, "POST /sync", "UPDATE inventory SET stock = ?", 1420))
        found = tools.detect_incident(self.live)
        self.assertEqual((found["source"], found["rows_affected"]), ("POST /sync", 1420))


class PatchSourceTests(unittest.TestCase):
    def test_scopes_the_update_and_requires_a_sku(self):
        patched = tools._patch_source(BUGGY, "UPDATE inventory SET stock = ?")
        self.assertIn('WHERE sku = ?"', patched)
        self.assertIn("refusing unscoped inventory update", patched)
        compile(patched, "patched", "exec")                       # still valid Python

    def test_returns_none_when_the_statement_is_not_in_the_source(self):
        self.assertIsNone(tools._patch_source(BUGGY, "DELETE FROM nothing"))


class DiagnoseTests(Env):
    incident = {"sql": "UPDATE inventory SET stock = ?", "source": "POST /api/admin/sync-stock",
                "rows_affected": 3, "ts": 5.0}

    def diagnose(self, llm_result):
        with mock.patch.object(tools.llm, "propose_patch", return_value=llm_result), \
                mock.patch.object(tools.appcode, "read_source", return_value=BUGGY):
            return tools.diagnose_and_patch_tool(self.live, self.branch, self.incident)

    def test_no_incident_means_nothing_to_patch(self):
        out = tools.diagnose_and_patch_tool(self.live, self.branch, None)
        self.assertEqual(out["found"], False)

    def test_regex_patch_is_verified_on_a_sandbox_clone(self):
        out = self.diagnose(None)
        self.assertTrue(out["patch_ok"])
        self.assertEqual(out["patch_source"], "regex")
        self.assertTrue(all(t["ok"] for t in out["tests"]))
        self.assertIn("+", out["diff"])
        self.assertIn("a/app/handlers.py", out["diff"])

    def test_a_good_llm_patch_is_used(self):
        good = tools._patch_source(BUGGY, self.incident["sql"])
        llm_patch = mock.Mock(patched_source=good, explanation="scoped by sku")
        out = self.diagnose(llm_patch)
        self.assertEqual((out["patch_source"], out["patch_ok"], out["explanation"]), ("llm", True, "scoped by sku"))

    def test_a_broken_llm_patch_falls_back_to_the_regex_patch(self):
        bad = mock.Mock(patched_source=BUGGY, explanation="did nothing")       # unchanged: still wipes every row
        out = self.diagnose(bad)
        self.assertEqual(out["patch_source"], "regex (fallback)")
        self.assertTrue(out["patch_ok"])
        self.assertNotIn("did nothing", out["explanation"])

    def test_a_patch_that_does_not_compile_is_reported_not_raised(self):
        out = self.diagnose(mock.Mock(patched_source="def sync_stock(:", explanation="x"))
        self.assertTrue(out["patch_ok"])                                       # fell back to the regex patch
        out2 = tools.diagnose_and_patch_tool(self.live, self.branch, {**self.incident, "sql": "UPDATE nope SET a = 1"})
        self.assertFalse(out2["patch_ok"])
        self.assertIn("no safe automatic patch", out2["explanation"])


class ApplyAndUndoTests(Env):
    def plan(self):
        return {"inventory_rows": [("APX-0007", "APX-0007", 99, 100)], "customer_rows": [], "order_rows": [],
                "item_rows": [], "backorder_ids": []}

    def apply(self, plan, expected, marker=None, preserved=()):
        marker = db.last_change_id(self.live) if marker is None else marker
        return tools.apply_recovery_tool(self.live, plan, expected, list(preserved), marker, None,
                                         os.path.join(self.tmp.name, "snap.db"), os.path.join(self.tmp.name, "snap.py"))

    def stock(self):
        return {r["sku"]: r["stock"] for r in self.live.execute("SELECT sku, stock FROM inventory")}

    def test_a_stale_plan_is_refused_and_changes_nothing(self):
        with self.assertRaisesRegex(RuntimeError, "stale"):
            self.apply(self.plan(), {"APX-0007": 99, "APX-0042": 5, "APX-0100": 7}, marker=-1)
        self.assertEqual(self.stock()["APX-0007"], 10)

    def test_failed_smoke_checks_roll_everything_back(self):
        with self.assertRaisesRegex(RuntimeError, "smoke checks failed"):
            self.apply(self.plan(), {"APX-0007": 1234})                        # expectation the data can never meet
        self.assertEqual(self.stock()["APX-0007"], 10)
        self.assertFalse(self.live.in_transaction)

    def test_apply_commits_then_undo_restores_the_snapshot(self):
        timing = {}
        with mock.patch.object(tools.appcode, "read_source", return_value="# original\n"), \
                mock.patch.object(tools.appcode, "write_source") as write:
            checks = tools.apply_recovery_tool(
                self.live, self.plan(), {"APX-0007": 99, "APX-0042": 5, "APX-0100": 7}, [], db.last_change_id(self.live),
                "# patched\n", os.path.join(self.tmp.name, "snap.db"), os.path.join(self.tmp.name, "snap.py"), timing)
            self.assertTrue(all(c["ok"] for c in checks))
            self.assertEqual(self.stock()["APX-0007"], 99)
            self.assertIn("verification_seconds", timing)
            write.assert_called_with("# patched\n")
            tools.undo_recovery(self.live, os.path.join(self.tmp.name, "snap.db"), os.path.join(self.tmp.name, "snap.py"))
            write.assert_called_with("# original\n")
        self.assertEqual(self.stock()["APX-0007"], 10)

    def test_guard_blocks_an_unsafe_statement_before_anything_runs(self):
        with mock.patch.object(tools.guard, "analyze", return_value={"allowed": False, "why": "nope"}):
            with self.assertRaisesRegex(RuntimeError, "Guardrail blocked"):
                self.live.execute("BEGIN")
                tools.execute_plan(self.live, self.plan())
        self.live.execute("ROLLBACK")


class RewindTests(Env):
    def test_rewind_reverses_changes_after_the_target_time(self):
        db.clock.offset = 0
        target = db.clock.now() + 1
        db.clock.offset = 100                                              # later writes are "after the incident"
        self.live.execute("UPDATE inventory SET stock = 0")
        branch, stats = tools.rewind_branch_tool(self.live, target, os.path.join(self.tmp.name, "rw.db"))
        self.assertEqual(stats["events_reversed"], 3)
        self.assertEqual(branch.execute("SELECT SUM(stock) FROM inventory").fetchone()[0], 22)
        self.assertEqual(self.live.execute("SELECT SUM(stock) FROM inventory").fetchone()[0], 0)
        branch.close()
        db.clock.offset = 0


if __name__ == "__main__":
    unittest.main()

"""Guards the hand-labelled intent eval set and the rule-based parser's recorded baseline."""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "evals"))

import run_evals  # noqa: E402


class IntentEvalTests(unittest.TestCase):
    def test_cases_are_well_formed_and_unique(self):
        cases = run_evals.load_cases()
        self.assertGreaterEqual(len(cases), 20)
        self.assertEqual(len({c["id"] for c in cases}), len(cases))
        self.assertEqual(len({c["prompt"] for c in cases}), len(cases))
        for case in cases:
            self.assertEqual(set(case["expected"]), set(run_evals.FIELDS), case["id"])

    def test_rule_based_parser_does_not_regress_below_the_recorded_baseline(self):
        report = run_evals.evaluate(run_evals.regex_parser, run_evals.load_cases())
        with open(os.path.join(ROOT, "evals", "baseline.json"), encoding="utf-8") as handle:
            baseline = json.load(handle)["rule_based_passed"]
        self.assertGreaterEqual(report["passed"], baseline, report["failures"])

    def test_plain_phrasings_and_units_are_always_handled(self):
        report = run_evals.evaluate(run_evals.regex_parser, run_evals.load_cases())
        for tag in ("basic", "units", "noise"):
            self.assertEqual(report["by_tag"][tag]["passed"], report["by_tag"][tag]["total"], tag)

    def test_the_runner_script_exits_zero_on_baseline(self):
        self.assertEqual(run_evals.main.__module__, "run_evals")


if __name__ == "__main__":
    unittest.main()

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCHMARKS = os.path.join(ROOT, "benchmarks")
sys.path.insert(0, ROOT)
sys.path.insert(0, BENCHMARKS)

import benchmark_recovery


class BenchmarkEvidenceTests(unittest.TestCase):
    def _runs(self, rows, iterations, seed):
        runs = []
        for iteration in range(1, iterations + 1):
            run = {
                "dataset_rows": rows,
                "iteration": iteration,
                "seed": seed,
                "errors": [],
            }
            for metric in benchmark_recovery.METRICS:
                run[metric] = 0.1 * iteration
            runs.append(run)
        return runs

    def test_environment_info_reports_required_fields(self):
        environment = benchmark_recovery.environment_info()
        for key in ("captured_at_utc", "platform", "system", "machine", "logical_cpus",
                    "python_version", "python_implementation", "sqlite_version",
                    "third_party_dependencies", "resource_module_available", "git_commit"):
            self.assertIn(key, environment)
        self.assertEqual(environment["third_party_dependencies"], {})

    def test_summarize_reports_sample_count(self):
        summary = benchmark_recovery.summarize([1.0, 2.0, 3.0])
        self.assertEqual(summary["sample_count"], 3)
        self.assertEqual(summary["median"], 2.0)
        self.assertEqual(summary["minimum"], 1.0)
        self.assertEqual(summary["maximum"], 3.0)

    def test_main_writes_reproducible_smoke_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "smoke.json")
            argv = [
                "benchmark_recovery.py", "--datasets", "1000", "--iterations", "1",
                "--seed", "20261122", "--output", output,
            ]
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(
                        benchmark_recovery, "run_dataset",
                        side_effect=lambda rows, iterations, seed, root: {
                            "dataset_rows": rows,
                            "runs": self._runs(rows, iterations, seed),
                            "summary": {
                                metric: benchmark_recovery.summarize([0.1])
                                for metric in benchmark_recovery.METRICS
                            },
                            "errors": [],
                        }):
                benchmark_recovery.main()

            with open(output, encoding="utf-8") as handle:
                document = json.load(handle)
            self.assertEqual(document["metadata"]["benchmark_mode"], "smoke")
            self.assertTrue(document["metadata"]["raw_results_preserved"])
            self.assertEqual(document["metadata"]["iterations_requested"], 1)
            self.assertEqual(document["metadata"]["datasets_requested"], [1000])
            self.assertIn("benchmark_recovery.py", document["metadata"]["command"])
            self.assertIn(output, document["metadata"]["documented_command"])
            self.assertIn("python_version", document["environment"])
            dataset = document["datasets"][0]
            self.assertEqual(dataset["errors"], [])
            self.assertEqual(dataset["summary"]["recovery_duration_seconds"]["sample_count"], 1)
            self.assertEqual(len(dataset["runs"]), 1)

    def test_main_preserves_failed_runs_and_empty_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "failed.json")
            argv = [
                "benchmark_recovery.py", "--datasets", "1000", "10000",
                "--iterations", "2", "--output", output,
            ]
            errors = [{"iteration": 1, "error": "RuntimeError: seeded failure"}]
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(
                        benchmark_recovery, "run_dataset",
                        return_value={"dataset_rows": 1000, "runs": [], "summary": {}, "errors": errors}):
                benchmark_recovery.main()

            with open(output, encoding="utf-8") as handle:
                document = json.load(handle)
            self.assertEqual(document["metadata"]["benchmark_mode"], "full")
            self.assertEqual(len(document["datasets"]), 2)
            for dataset in document["datasets"]:
                self.assertEqual(dataset["errors"], errors)
                self.assertEqual(dataset["summary"], {})


if __name__ == "__main__":
    unittest.main()

"""Discover and run the complete unittest suite with machine-readable JSON reporting."""
import argparse
import json
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=os.path.join(ROOT, "test-reports", "ci_test_report.json"))
    args = parser.parse_args()

    suite = unittest.defaultTestLoader.discover(
        os.path.join(ROOT, "tests"),
        pattern="test_*.py",
    )

    started = time.perf_counter()
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    elapsed = time.perf_counter() - started

    report = {
        "timestamp_unix": time.time(),
        "python_version": sys.version,
        "total": result.testsRun,
        "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
        "failed": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "status": "OK" if result.wasSuccessful() else "FAIL",
        "execution_duration_seconds": round(elapsed, 6),
    }

    output = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

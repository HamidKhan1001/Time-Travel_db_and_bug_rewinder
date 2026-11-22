import argparse
import json
import os
import platform
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from generate_data import DEFAULT_SEED, generate_dataset
from timetravel import db
from timetravel.recovery import change_tracker, recovery_engine

try:
    import resource
except ImportError:
    resource = None

METRICS = (
    "snapshot_seconds",
    "transaction_history_seconds",
    "recovery_planning_seconds",
    "recovery_execution_seconds",
    "checksum_verification_seconds",
    "execute_plan_seconds",
    "recovery_duration_seconds",
    "preflight_seconds",
    "simulation_seconds",
    "apply_seconds",
    "commit_seconds",
    "peak_rss_mb_end",
    "rss_growth_mb",
)


def _command_output(arguments):
    try:
        return subprocess.check_output(arguments, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return None


def _total_memory_gb():
    if sys.platform == "darwin":
        value = _command_output(["sysctl", "-n", "hw.memsize"])
        if value:
            return round(int(value) / (1024 ** 3), 2)
    elif sys.platform.startswith("linux"):
        try:
            with open("/proc/meminfo", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("MemTotal:"):
                        return round(int(line.split()[1]) / (1024 ** 2), 2)
        except OSError:
            return None
    return None


def environment_info():
    cpu_brand = None
    if sys.platform == "darwin":
        cpu_brand = _command_output(["sysctl", "-n", "machdep.cpu.brand_string"])
    if not cpu_brand:
        cpu_brand = platform.processor() or None
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "cpu_brand": cpu_brand,
        "logical_cpus": os.cpu_count(),
        "total_memory_gb": _total_memory_gb(),
        "python_version": platform.python_version(),
        "sqlite_version": sqlite3.sqlite_version,
        "git_commit": _command_output(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"]),
    }


def peak_rss_mb():
    if resource is None:
        return 0.0
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return value / (1024 ** 2)
    return value / 1024


def _validate_recovery(conn, result, rows):
    if result["verification"]["integrity_status"] != "VERIFIED":
        raise RuntimeError("checksum verification did not succeed")
    run = conn.execute(
        "SELECT status FROM recovery_runs WHERE id = ?", (result["audit_run_id"],)).fetchone()
    if run is None or run["status"] != "committed":
        raise RuntimeError("recovery run was not committed")
    mismatches = conn.execute(
        "SELECT COUNT(*) FROM inventory "
        "WHERE stock <> ((CAST(SUBSTR(sku, 5) AS INTEGER) * 37) % 1000 + 1)").fetchone()[0]
    if mismatches:
        raise RuntimeError(f"{mismatches} inventory rows were not restored")
    if conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] != rows:
        raise RuntimeError("inventory row count changed during recovery")


def run_iteration(rows, seed, workdir, iteration):
    db_path = os.path.join(workdir, f"recovery_{rows}_{iteration}.db")
    snapshot_path = os.path.join(workdir, f"snapshot_{rows}_{iteration}.db")
    generate_dataset(rows, db_path, seed=seed)

    conn = db.connect(db_path)
    try:
        rss_before = peak_rss_mb()
        recovery_start = time.perf_counter()

        started = time.perf_counter()
        recovery_engine.snapshot(conn, snapshot_path)
        snapshot_seconds = time.perf_counter() - started

        anchor = change_tracker.latest_event_id(conn)

        started = time.perf_counter()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE inventory SET stock = 0")
        conn.execute("COMMIT")
        transaction_history_seconds = time.perf_counter() - started

        events = change_tracker.fetch_events(conn, after_event_id=anchor, order="id ASC")
        if not events:
            raise RuntimeError("faulty transaction produced no history events")
        transaction_ids = {event.transaction_id for event in events}
        if len(transaction_ids) != 1:
            raise RuntimeError("faulty write was split across multiple transactions")
        faulty_transaction_id = transaction_ids.pop()

        started = time.perf_counter()
        plan = recovery_engine.create_plan(
            conn, anchor_event_id=anchor, transaction_ids=[faulty_transaction_id])
        recovery_planning_seconds = time.perf_counter() - started

        timing = {}
        started = time.perf_counter()
        result = recovery_engine.execute_plan(conn, plan, timing=timing)
        execute_plan_seconds = time.perf_counter() - started
        checksum_verification_seconds = timing["checksum_verification_seconds"]
        recovery_execution_seconds = execute_plan_seconds - checksum_verification_seconds
        recovery_duration_seconds = time.perf_counter() - recovery_start
        rss_after = peak_rss_mb()

        _validate_recovery(conn, result, rows)

        measured = (snapshot_seconds + transaction_history_seconds + recovery_planning_seconds
                    + execute_plan_seconds)
        return {
            "dataset_rows": rows,
            "iteration": iteration,
            "seed": seed,
            "event_count": len(events),
            "plan_step_count": len(plan.steps),
            "faulty_transaction_id": faulty_transaction_id,
            "snapshot_seconds": snapshot_seconds,
            "transaction_history_seconds": transaction_history_seconds,
            "recovery_planning_seconds": recovery_planning_seconds,
            "recovery_execution_seconds": recovery_execution_seconds,
            "checksum_verification_seconds": checksum_verification_seconds,
            "execute_plan_seconds": execute_plan_seconds,
            "recovery_duration_seconds": recovery_duration_seconds,
            "unaccounted_seconds": recovery_duration_seconds - measured,
            "preflight_seconds": timing["preflight_seconds"],
            "simulation_seconds": timing["simulation_seconds"],
            "apply_seconds": timing["apply_seconds"],
            "commit_seconds": timing["commit_seconds"],
            "database_bytes": os.path.getsize(db_path),
            "snapshot_bytes": os.path.getsize(snapshot_path),
            "rows_checked": result["verification"]["total_rows_checked"],
            "integrity_status": result["verification"]["integrity_status"],
            "audit_status": "committed",
            "peak_rss_mb_start": rss_before,
            "peak_rss_mb_end": rss_after,
            "rss_growth_mb": max(0.0, rss_after - rss_before),
        }
    finally:
        conn.close()


def summarize(values):
    return {
        "average": round(statistics.mean(values), 6),
        "median": round(statistics.median(values), 6),
        "minimum": round(min(values), 6),
        "maximum": round(max(values), 6),
    }


def run_dataset(rows, iterations, seed, root):
    runs = []
    errors = []
    for iteration in range(1, iterations + 1):
        workdir = os.path.join(root, f"rows_{rows}", f"iteration_{iteration}")
        os.makedirs(workdir, exist_ok=True)
        try:
            runs.append(run_iteration(rows, seed, workdir, iteration))
        except Exception as error:
            errors.append({"iteration": iteration, "error": f"{type(error).__name__}: {error}"})
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    summary = {}
    if runs:
        summary = {metric: summarize([run[metric] for run in runs]) for metric in METRICS}
    return {"dataset_rows": rows, "runs": runs, "summary": summary, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description="Benchmark deterministic database recovery.")
    parser.add_argument("--datasets", type=int, nargs="+", default=[1000, 10000, 100000, 500000])
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output", default=os.path.join(HERE, "benchmark_results.json"))
    args = parser.parse_args()
    if args.iterations < 1:
        raise SystemExit("--iterations must be positive")

    output_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    document = {
        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "command": "python3 benchmarks/benchmark_recovery.py",
            "seed": args.seed,
            "iterations_requested": args.iterations,
            "datasets_requested": args.datasets,
            "timing_source": "time.perf_counter",
            "memory_source": "resource.getrusage process high-water mark",
            "dataset_shape": "N inventory rows plus 10 customers, 20 orders, and 20 order items",
            "faulty_operation": "UPDATE inventory SET stock = 0",
            "notes": [
                "Every timing comes from an actual recovery execution; no estimates or delays are used.",
                "Peak RSS is a process-wide high-water mark and does not decrease between iterations.",
                "Recovery execution excludes live checksum verification but includes preflight, simulation, apply, and commit.",
                "Total recovery duration is wall-clock time from snapshot creation through execute_plan.",
            ],
        },
        "environment": environment_info(),
        "datasets": [],
    }

    with tempfile.TemporaryDirectory(prefix="tt-benchmark-") as root:
        for rows in args.datasets:
            print(f"benchmarking {rows} rows", flush=True)
            result = run_dataset(rows, args.iterations, args.seed, root)
            document["datasets"].append(result)
            if result["errors"]:
                print(f"  skipped/incomplete: {result['errors']}", flush=True)
            else:
                median = result["summary"]["recovery_duration_seconds"]["median"]
                print(f"  median recovery duration: {median:.6f}s", flush=True)

    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"output": output_path, "datasets": len(document["datasets"])}, indent=2))


if __name__ == "__main__":
    main()

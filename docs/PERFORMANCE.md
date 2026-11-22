# Phase 5 Performance And Integrity Evidence

This document records measured local performance evidence and checksum-integrity scope for the current working tree. It does not claim production, Postgres, AWS, distributed, or SLA performance.

## Current benchmark run

The current evidence was generated on `2026-11-22T17:41:49+00:00` from commit `bff18b1`. The Phase 5 working-tree changes were present but uncommitted when the benchmark was generated.

Environment from `test-reports/phase5-benchmark-full.json`:

- Windows `11-10.0.26200-SP0`, AMD64, 12 logical CPUs
- CPython `3.13.1`, MSC v.1942 64-bit, SQLite `3.45.3`
- CPU: `AMD64 Family 25 Model 80 Stepping 0, AuthenticAMD`
- Seed: `20261122`
- Timing source: `time.perf_counter`
- Memory source: `resource.getrusage` high-water mark, unavailable on Windows

Commands:

```bash
python benchmarks/benchmark_recovery.py --datasets 1000 --iterations 1 --output test-reports/phase5-benchmark-smoke.json
python benchmarks/benchmark_recovery.py --datasets 1000 10000 --iterations 3 --output test-reports/phase5-benchmark-full.json
```

The smoke report is a single-iteration check. It recorded a `0.480735s` median recovery duration for 1000 rows. The three-repetition report below is the primary evidence.

| Inventory rows | Samples | Median recovery duration | Median recovery execution | Median checksum verify | Median planning | Median preflight | Median simulation | Median apply | Median commit |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1000 | 3 | 0.463355s | 0.394594s | 0.026730s | 0.012540s | 0.242259s | 0.056232s | 0.088855s | 0.005105s |
| 10000 | 3 | 4.692449s | 4.113598s | 0.212552s | 0.133658s | 2.454099s | 0.539473s | 1.053297s | 0.015316s |

Ten times the inventory rows produced about a `10.1x` increase in median total recovery duration. Both datasets completed all three iterations with empty `errors`, `audit_status: committed`, and `integrity_status: VERIFIED`. Raw runs and sample counts are preserved in `test-reports/phase5-benchmark-full.json`; summaries now include `sample_count`.

`peak_rss_mb_start`, `peak_rss_mb_end`, and `rss_growth_mb` are `0.0` because the `resource` module is unavailable on Windows. These are not measured zero-memory results and must not be reported as memory efficiency evidence.

## Benchmark evidence classification

Current, directly generated evidence:

- `test-reports/phase5-benchmark-smoke.json` — genuine 1000-row single-iteration smoke run.
- `test-reports/phase5-benchmark-full.json` — genuine 1000/10000-row, three-iteration benchmark with raw runs.

Historical evidence preserved but not mixed into current medians:

- `benchmarks/benchmark_results.json` — older full benchmark from a different environment and commit.
- `test-reports/phase1-benchmark-smoke.json`, `phase2-benchmark-smoke.json`, `phase2-final-benchmark-smoke.json`, `phase3-benchmark-smoke.json`, `phase3-independent-benchmark-smoke.json` — genuine historical smoke runs with earlier commits, mostly single iteration.

`docs/devlog.md` contains historical planning notes such as “No benchmark” and “No checksum”; those lines describe earlier planning state and are superseded by this document and `docs/AUDIT.md`.

## Timing implementation

HTTP recovery workflows now expose an additive `timings` object on session JSON and in selected audit details:

- `planning_preview_seconds` — merge planning plus read-only preview projection.
- `approval_delay_seconds` — approval acceptance to execution start.
- `recovery_execution_seconds` — HTTP apply/cutover duration.
- `verification_seconds` — post-apply smoke checks, not checksum verification.
- `undo_seconds` — separate undo duration.
- `total_workflow_seconds` — session creation to first terminal applied/error phase.

All values use `time.perf_counter()` and are `null` when the stage did not run. Wall-clock fields such as `created`, `generated_at`, and `completed_at` remain timestamps and are never used as elapsed durations. Timing values are in-memory and are not restored after process restart.

The benchmark script was not duplicated. `benchmarks/benchmark_recovery.py` now records the actual command, documented command, benchmark mode, raw-result preservation flag, Python implementation/compiler, third-party dependency set, and resource-module availability.

## Integrity scope

Checksum verification is implemented in `timetravel/recovery/verification.py` and exercised by the separate recovery engine and deterministic tests.

Covered tables are the four business tables in `db.TABLES`:

- `customers`
- `inventory`
- `orders`
- `order_items`

The digest covers full row content and primary keys for those tables. Tests verify stable digests for unchanged state, all-business-table coverage, modified rows, missing rows, unexpected rows, primary-key mismatches, and rollback when checksum verification fails. `query_log`, `changelog`, audit tables, schema, indexes, triggers, and HTTP smoke checks are outside this checksum scope.

The HTTP session path intentionally reports checksum verification as `unavailable`. Checksum evidence should not be presented as an HTTP UI verification step. The `verification_seconds` HTTP timing measures post-apply smoke checks only.

## Validation

- `python -m compileall -q benchmarks tests timetravel server.py` — passed.
- `python -m unittest discover -s tests` — `165` tests, `OK`.
- Benchmark commands above — completed with preserved raw results and no failed iterations.
- `tests/test_recovery_timing.py` — verifies timing contract, failure path timing, undo timing, and audit details.
- `tests/test_benchmark_evidence.py` — verifies benchmark metadata, sample counts, reproducible report writing, and preserved error reporting.
- `tests/test_integrity_verification.py` — verifies checksum coverage, stability, mismatch detection, and scope limits.

## Limitations

- Three samples per dataset are enough for local evidence, not a production SLA.
- Results are from one Windows developer workstation; historical reports are not hardware-comparable.
- Benchmark total duration excludes the human approval wait; HTTP `total_workflow_seconds` includes it.
- Memory metrics were unavailable on Windows.
- Checksum verification does not cover metadata tables, audit tables, or schema objects.
- No external database, cloud deployment, distributed system, or network latency was tested.

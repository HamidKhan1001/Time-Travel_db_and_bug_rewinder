# Database Engine README

This document describes the Task 3 Database Recovery Engine in `timetravel/recovery/` and how it fits into the Time-Travel DB project.

## Implemented features

- **Durable transaction history**: transaction IDs, event sequence, timestamp, table, PK, operation, and old/new values (`transaction_logger.py`, `change_tracker.py`).
- **Deterministic recovery planner**: read-only analysis builds a compensating `RecoveryPlan` with fingerprint and execution order (`recovery_planner.py`).
- **Recovery execution engine**: validates, simulates, applies atomically, records audit rows, and rolls back on failure (`recovery_engine.py`).
- **INSERT/UPDATE/DELETE recovery**: compensating operations restore previous values, restore deleted rows, and remove faulty inserts.
- **FK-aware recovery**: inspects foreign keys, builds dependency edges, orders steps safely, and detects FK conflicts (`dependencies.py`, `integrity.py`).
- **Checksum verification**: SHA-256 row-level comparison over the configured business tables; mismatch blocks success (`verification.py`).
- **Two crash scenarios**: the inventory stock wipe uses the agent HITL workflow; the orders status wipe uses this engine directly through `tests/setup_second_crash.py` and `tests/run_second_crash.py`.
- **Benchmark scripts**: reproducible local SQLite benchmarks in `benchmarks/`. Preserved measurements are listed in [`BENCHMARK_REPORT.md`](BENCHMARK_REPORT.md) and [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md).

## Key modules

| File | Purpose |
|---|---|
| `timetravel/db.py` | SQLite connection/schema/CDC hooks; installs recovery history additively. |
| `timetravel/recovery/transaction_logger.py` | Durable history schema, triggers, transaction/event sequencing. |
| `timetravel/recovery/change_tracker.py` | Read-only event/transaction access. |
| `timetravel/recovery/recovery_planner.py` | Deterministic compensating plan generation. |
| `timetravel/recovery/dependencies.py` | FK inspection and dependency ordering. |
| `timetravel/recovery/integrity.py` | Plan/schema/conflict/FK/uniqueness validation. |
| `timetravel/recovery/verification.py` | SHA-256 checksum baselines and verification reports. |
| `timetravel/recovery/recovery_engine.py` | Atomic execution, audit, rollback, and verification gate. |

## Integration boundaries

- Existing API contracts were preserved; no routes were renamed or removed.
- `timetravel/recovery/` is additive.
- The legacy demo flow (`server.py` → `agent.py` → `tools.py`) still uses the HITL approval gate at `/api/rewind` and `/api/session/<id>/approve`.
- `final_recovery_demo.py` also uses the agent HITL gate and then performs separate business-table checksum verification.
- The second crash scripts and benchmarks call `recovery_engine.create_plan()` / `execute_plan()` directly; they do not use HTTP approval.

## Safety model

- Analysis and execution are separated.
- Plans are validated and simulated before live apply.
- Recovery runs in controlled SQLite transactions and rolls back on failure.
- Conflicts and unsupported cases fail safely.
- Checksum verification failure prevents committed success.
- The engine does not execute arbitrary AI-generated SQL.

## Verification commands

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
TT_PACE=0 python3 tests/e2e_isolated.py
python3 tests/setup_second_crash.py --dir "$tmpdir"
python3 tests/run_second_crash.py --dir "$tmpdir"
```

`tests/e2e.py`, `reset.py`, `/api/demo/reset`, and `final_recovery_demo.py` can modify repository demo state. Prefer the isolated E2E runner when preserving repository files matters.

## Benchmark commands

```bash
# Local smoke evidence; use a new output path to avoid overwriting preserved reports.
python3 benchmarks/benchmark_recovery.py --datasets 1000 --iterations 1 --output test-reports/local-benchmark-smoke.json

# Larger local evidence run; may take significant time.
python3 benchmarks/benchmark_recovery.py --datasets 1000 10000 100000 500000 --iterations 3 --output test-reports/local-benchmark-full.json
```

These are reproduction commands, not a claim that every command has been run in the current workspace. Historical measured results are in [`BENCHMARK_REPORT.md`](BENCHMARK_REPORT.md). Do not fabricate benchmark results; if a run does not complete, report it as not completed.

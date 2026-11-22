# Database Engine README

This document describes the Task 3 Database Recovery Engine implemented in `timetravel/recovery/` and how it integrates with the existing Time-Travel DB project.

## Completed feature list

- **Durable transaction history**: transaction IDs, event sequence, timestamp, table, PK, op, old/new values (`transaction_logger.py`, `change_tracker.py`).
- **Deterministic recovery planner**: read-only analysis builds compensating `RecoveryPlan` with fingerprint and execution order (`recovery_planner.py`).
- **Recovery execution engine**: validates, simulates, applies atomically, records audit rows, rolls back on failure (`recovery_engine.py`).
- **UPDATE/DELETE/INSERT recovery**: compensating operations restore previous values, restore deleted rows, and remove faulty inserts.
- **FK-aware recovery**: inspects foreign keys, builds dependency graph, orders steps dependency-safely, detects FK conflicts (`dependencies.py`, `integrity.py`).
- **Checksum verification**: SHA-256 row/database checksums; mismatch blocks success (`verification.py`).
- **Second crash scenario**: independent orders-status unscoped UPDATE using same logger/planner/engine/verification (`tests/setup_second_crash.py`, `tests/run_second_crash.py`).
- **Automated tests**: 86 unittest tests passing, including Phase 9 comprehensive suite.
- **Benchmark suite**: reproducible scripts in `benchmarks/` (actual results must be generated on target machine; no fabricated values).

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
| `timetravel/recovery/recovery_engine.py` | Atomic execution, audit, rollback, verification gate. |

## Backend integration

- Existing API contracts were preserved; no routes were renamed/removed.
- Recovery engine is additive under `timetravel/recovery/`.
- `timetravel/db.py` was minimally modified to install durable recovery history on connections/schema; existing CDC/changelog behavior remains.
- Legacy demo flow (`server.py` -> `agent.py` -> `tools.py`) still uses existing HITL approval gate (`/api/rewind`, `/api/session/{id}/approve`) before applying recovery.
- The final demonstration script uses the same approval gate by calling `agent.approve()` only after explicit human confirmation.

## Safety model

- Analysis and execution are separated.
- Plans are validated and simulated before live apply.
- Recovery runs in controlled DB transactions and rolls back on failure.
- Conflicts/unsupported cases fail safely with errors/conflicts.
- Checksum verification failure prevents committed success.
- No arbitrary AI-generated SQL is executed by the recovery engine.

## Quick verification commands

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 tests/e2e.py
python3 tests/final_recovery_demo.py
```

## Benchmark commands

```bash
# Recommended: run on stable machine; can take significant time.
python3 benchmarks/benchmark_recovery.py --datasets 1000 10000 100000 500000 --iterations 3 --output benchmarks/benchmark_results.json

# Minimum Phase 10 evidence target (100K+), actual measured run:
python3 benchmarks/benchmark_recovery.py --datasets 100000 --iterations 1 --output benchmarks/benchmark_results_100k.json
```

Do not fabricate benchmark results. If a run does not complete, report it as not completed.

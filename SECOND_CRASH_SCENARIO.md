# Second Independent Crash Scenario

Phase 5 adds a second, independent recovery demonstration that does **not** reuse the inventory-stock bug. It uses a faulty unscoped `UPDATE` on `orders.status` in an isolated SQLite database.

This scenario uses the documented **direct recovery-engine workflow**: the scripts call the shared planner, integrity checks, and executor directly. It does **not** use the agent, HTTP API, UI, or human-in-the-loop approval gate. The inventory scenario remains the HITL demonstration.

## Goal

Show that the same durable transaction history, planner, integrity checks, and recovery engine can recover a different kind of accidental multi-row write while preserving a legitimate transaction that happened after the fault.

The inventory scenario remains available in `tests/e2e.py`. This scenario uses a separate database file and touches only `orders` after the anchor.

## Files

| File | Purpose |
|---|---|
| `tests/setup_second_crash.py` | Creates the isolated DB, seeds fixed customers/orders, captures original state, writes `second_crash_state.json`. |
| `tests/run_second_crash.py` | Runs the faulty UPDATE, scopes recovery to the faulty transaction, executes the shared engine, verifies state, writes `second_crash_report.json`. |
| `tests/test_second_crash_scenario.py` | Automated tests for the second scenario and for the original inventory scenario. |
| `SECOND_CRASH_SCENARIO.md` | This document. |

At implementation time, no application module, API route, UI file, seed fixture, or existing recovery tool signature was changed. Current status and preserved evidence are described in [`DATABASE_LIMITATIONS.md`](DATABASE_LIMITATIONS.md) and [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md).

## Run it

From the repository root:

```bash
tmpdir=$(mktemp -d)
python3 tests/setup_second_crash.py --dir "$tmpdir"
python3 tests/run_second_crash.py --dir "$tmpdir"
```

If `--dir` is omitted, the setup script creates a fresh temporary directory and prints its path. Pass that same directory to the run script to preserve the two-step setup/execution flow.

The scripts create only these files in the chosen directory:

- `second_crash.db`
- `second_crash_state.json`
- `second_crash_report.json`

They never touch `data/live.db`.

## Scenario details

Seeded data:

- Customers `1` and `2`.
- Orders `2001`–`2004` with distinct statuses: `paid`, `pending`, `shipped`, `paid`.
- Anchor is the durable transaction-history event ID captured after seeding.

Faulty operation:

```sql
UPDATE orders SET status = 'cancelled'
```

The operation was intended for order `2004` only, but because the statement is unscoped it changes all four orders.

Legitimate unrelated transaction:

- Order `2005` is inserted after the faulty transaction with status `paid`.
- The recovery plan is scoped with `transaction_ids=[faulty_transaction_id]`, so order `2005` is not reversed.

## Recovery flow

1. `setup_second_crash.py` captures all captured business-table rows and a checksum before the fault.
2. `run_second_crash.py` rechecks that captured state before executing the fault.
3. The faulty UPDATE runs inside one explicit `BEGIN IMMEDIATE` transaction, so all four changes share one durable transaction ID.
4. Affected records are read from `transaction_history`; each record includes event ID, order ID, before status, and after status.
5. The plan is produced by `recovery_engine.create_plan(...)` using the same `recovery_planner` as every other scenario.
6. The plan is applied by `recovery_engine.execute_plan(...)` in one atomic recovery transaction.
7. Verification uses the existing `integrity` module plus Phase 6 checksum verification: engine checks, `PRAGMA foreign_key_check`, per-relationship orphan checks, original status comparison, expected final table state including the legitimate order, and row-level checksum comparison against the expected post-recovery state.
8. The script writes a JSON recovery report and exits with a `FAIL` report if any check fails.

This scenario does not create another logger, planner, integrity layer, or executor. It reuses:

- `timetravel.recovery.transaction_logger` through `db.connect()` / `db.create_schema()`.
- `timetravel.recovery.change_tracker`.
- `recovery_engine.create_plan()` / `recovery_engine.execute_plan()`.
- `integrity.checksum()` / `integrity.verify_foreign_keys()` / `verification.checksum_database()`.
- `explain_plan()` for the report.

## Recovery report

`second_crash_report.json` contains:

- `status`: `PASS` or `FAIL`.
- `scenario`: stable scenario name.
- `anchor_event_id`, `faulty_transaction_id`, `legitimate_transaction_id`.
- `faulty_sql`, `intended_order_id`, `faulty_rowcount`.
- `affected_tables`, `affected_count`, `affected_records`.
- `plan`: deterministic planner summary, including selected transaction IDs and execution order.
- `recovery`: audit run ID, applied step count, fingerprint, and execution order.
- `checksums`: original, after-fault, and final checksums.
- `verification`: engine checks, FK checks, checksum verification report, restored-status flag, preserved-order flag, and expected-state match.
- `final_orders`: the final `orders` rows.

Checksums and `created_at` values are computed at run time; they are not hardcoded or fabricated.

## Automated tests

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The new tests prove:

- the orders-status crash restores all four original statuses;
- only the faulty transaction is selected for reversal;
- the legitimate order `2005` survives;
- all engine and FK checks pass;
- the JSON report is written with `status: PASS`;
- the original inventory-stock recovery still works through the same engine while preserving a later legitimate order.

## Verified results

Last verified from the repository root:

- `test_orders_status_crash_scenario`: PASS.
- `test_inventory_crash_scenario_still_works`: PASS.
- Historical Phase 9 snapshot: 86 tests pass; the current suite count is recorded in [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md).
- Manual two-script run: `status: PASS`, `faulty_rowcount: 4`, `affected_count: 4`, `affected_tables: ["orders"]`, legitimate order preserved, foreign keys valid, checksum `integrity_status: VERIFIED`.

The existing inventory e2e demo was also re-run in an isolated copy and passed.

## Limits

- The fault is an unscoped `UPDATE` on `orders`; it does not simulate a bad DDL migration.
- If a legitimate later transaction edits the same rows that the faulty transaction touched, the existing conflict detector will reject the scoped recovery rather than guess intent.
- The scenario is intentionally isolated and deterministic; it does not change the running demo database or app code.

Historical note: this document was completed during the recovery-engine phase. Later phase status and current repository evidence are documented in [`README.md`](README.md), [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md), and [`PRODUCTION_RECOVERY_ARCHITECTURE.md`](PRODUCTION_RECOVERY_ARCHITECTURE.md).

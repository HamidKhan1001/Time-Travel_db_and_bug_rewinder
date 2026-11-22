# Database Engine Limitations

This document describes the supported scope, known limitations, and remaining issues for the Time-Travel DB recovery engine as implemented in this repository.

## Supported scope (implemented and tested)

- SQLite database via Python stdlib `sqlite3`.
- Registered business tables in `timetravel/db.py`: `customers`, `inventory`, `orders`, `order_items`.
- Supported DML operations captured by recovery triggers: `INSERT`, `UPDATE`, `DELETE`.
- Deterministic recovery planning from durable `transaction_history` with analysis separated from execution.
- Atomic recovery execution in controlled SQLite transactions (`BEGIN IMMEDIATE`) with rollback on failure.
- Conflict detection before execution: duplicate PK, missing records, conflicting changes, unique constraints, FK dependency conflicts.
- FK-aware dependency ordering for supported single-column FK relationships.
- SHA-256 row/database checksum verification; recovery is not marked successful when verification fails.
- Two independent crash scenarios: inventory stock wipe (existing demo) and orders-status unscoped UPDATE (Phase 5 scripts/tests).

## Known limitations

| Limitation | Impact | Status |
|---|---|---|
| SQLite-specific implementation | Not a PostgreSQL/WAL/RDS production engine | By design for prototype |
| Capture scope limited to registered tables/DML | DDL, unmanaged tables, query_log/changelog/system tables, out-of-band writes not recovered by engine history | Documented/unsupported |
| Single-column primary keys in `db.TABLES` registry | Composite PKs not supported | Unsupported |
| PK-changing UPDATEs | Identity/child-reference reconstruction unsafe; rejected/unsupported in FK-aware flows | Unsupported |
| Complex FK patterns | Composite FKs, self-referential FKs, FKs to uncaptured tables/non-PK targets, dependency cycles can be rejected | Unsupported/fail-safe |
| Cascading side effects not explicitly captured/selected | Engine rejects dangerous cascade/loss cases rather than silently deleting legitimate rows | Fail-safe |
| Clock-based legacy changelog selection | `db.changes_after` uses timestamp; durable history uses event IDs/sequences and should be preferred | Legacy compatibility present |
| Compensation/synthetic events | Reversal operations can create changelog events; durable recovery history distinguishes audit/recovery records | Known behavior |
| Cross-resource cutover atomicity | DB recovery commit and legacy code patch write are separate steps in demo flow | Known limitation |
| Cross-process/concurrency | `db.LOCK` is process-local; stale-marker checks reduce but do not eliminate distributed TOCTOU | Prototype limitation |
| Benchmark environment sensitivity | 100K+ benchmark execution is resource/time intensive; full 500k x3 run may be impractical in constrained environment | Operational limitation |

## Remaining issues / operational notes

- **100K+ benchmark evidence**: benchmark scripts are implemented; a 100K single-iteration run was attempted during Phase 10 but did not complete within the available execution window in this session. No 100K result is fabricated. Run the command below on a stable machine and commit the generated JSON/report.
- **Full 1k/10k/100k/500k x3 matrix**: not completed in this workspace session; report only actual measured results.
- **PostgreSQL WAL/AWS RDS PITR**: documented as proposed architecture only; no native implementation claimed.
- **Legacy demo coupling**: `server.py`/`agent.py`/`tools.py` still contain the original demo recovery flow; `timetravel/recovery` is additive and can be used directly by scripts/tests.

## Safety guarantees in supported scope

- Unsafe/unsupported plans fail before or during controlled execution and do not report success.
- Checksum verification failure raises and prevents committed success status.
- Recovery execution uses transactions and rolls back on failure.
- Tests are isolated in temporary databases; no destructive test targets `data/live.db`.

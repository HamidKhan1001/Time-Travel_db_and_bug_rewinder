# 0001. Capture changes with triggers, not by reading the WAL

**Status:** accepted for the prototype.

## Context
Point-in-time recovery needs to know, for every row change, what the row looked like before and after. SQLite's write-ahead log is a physical page log; it does not give logical row images and is recycled by checkpoints. PostgreSQL logical decoding and RDS point-in-time recovery do give this, but need infrastructure a hackathon prototype and a laptop demo cannot assume.

## Decision
Install `AFTER INSERT/UPDATE/DELETE` triggers on the registered business tables (`customers`, `inventory`, `orders`, `order_items`). Each trigger writes a row to `changelog` with the table, operation, primary key and the old and new values as JSON. Rewind reverses the log from newest to oldest. Statements run through the app handlers are also written to `query_log`, which is how the incident (an unscoped write touching many rows) is found.

## Consequences
- Row-level before/after images with no external dependency, so rewind is exact and testable.
- Only DML on registered tables is captured. DDL, unregistered tables and writes made outside the instrumented connection are invisible (documented in [DATABASE_LIMITATIONS.md](../DATABASE_LIMITATIONS.md)).
- Write amplification: every change is written twice. Acceptable at demo scale; benchmarks are in [PERFORMANCE.md](../PERFORMANCE.md).
- The production path is PostgreSQL logical decoding or RDS PITR feeding the same plan format. That is a proposed design ([PRODUCTION_RECOVERY_ARCHITECTURE.md](../PRODUCTION_RECOVERY_ARCHITECTURE.md)), not implemented.

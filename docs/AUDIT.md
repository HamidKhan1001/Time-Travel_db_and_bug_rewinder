# Audit Persistence and Recovery Lifecycle

## Storage

The legacy demo session audit is stored in SQLite in the `session_audit_events` table.

| Column | Meaning |
|---|---|
| `id` | SQLite autoincrement identifier |
| `session_id` | Recovery session ID such as `INC-12ABC3` |
| `event_type` | Stable lifecycle event name |
| `status` | `started`, `approved`, `rejected`, `completed`, or `failed` |
| `ts` | Unix timestamp |
| `detail_json` | JSON object with safe, non-secret diagnostic values |

The table is created by `timetravel.db.connect()` and `timetravel.db.create_schema()` through `timetravel.audit.ensure_schema()`.

The recovery engine also persists:

- `recovery_runs`: run start/finish, fingerprint, anchor, selection, step count, status, and detail.
- `recovery_actions`: step-level operation, table, primary key, source event, and applied/failed status.
- `transaction_history` and `recovery_transactions`: captured durable transaction history.

These tables are SQLite records and survive database close/reopen. They do not provide external immutable audit infrastructure.

## Session lifecycle events

| Event | Status | Meaning |
|---|---|---|
| `recovery_initiated` | started | Session created |
| `recovery_preview_generated` | started | Merge/dry-run preview completed |
| `recovery_failed` | failed | Planning or pipeline failure |
| `approval_rejected` | rejected | Approval called in an invalid state |
| `approval_granted` | approved | Human approval accepted |
| `recovery_execution_started` | started | Approved cutover began |
| `recovery_completed` | completed | Recovery checks passed |
| `recovery_failed` | failed | Cutover or apply failed |
| `undo_rejected` | rejected | Undo called before applied state |
| `undo_initiated` | started | Undo started |
| `undo_completed` | completed | Snapshot/source restored |
| `undo_failed` | failed | Undo operation failed |
| `integrity_verified` | completed | Post-apply smoke/integrity checks passed |

Audit detail fields contain only safe summaries such as counts, risk scores, phase names, file-operation outcomes, and test/check summaries. Passwords and provider credentials are not recorded.

Phase 5 adds an optional `timings` object to preview, recovery, integrity, undo, and failure audit details. Values are monotonic elapsed seconds sourced from `time.perf_counter()`; a stage that did not run is represented by `null`. These values are diagnostic summaries, not a separate audit ledger and not wall-clock timestamps. The same object is exposed as `timings` on the in-memory session JSON described in `API.md`.

## Recovery lifecycle

1. `POST /api/rewind` creates a `Session` and records `recovery_initiated`.
2. Intent parsing determines the rewind target and preserve/remediate intent.
3. The live database is cloned and changelog changes are reversed on the clone.
4. Legitimate writes after the rewind target are extracted.
5. Inventory, FK, idempotency, and oversell checks generate a preview.
6. A patch is proposed and verified on a sandbox clone if remediation is requested.
7. The session enters `awaiting_approval` and records `recovery_preview_generated`.
8. `POST /api/session/<id>/approve` records `approval_granted`, `recovery_execution_started`, and success or failure.
9. The legacy engine creates a database snapshot and applies the plan transactionally.
10. If apply succeeds, source code is optionally replaced and `recovery_completed` is recorded.
11. `POST /api/session/<id>/undo` records undo initiation, success, or failure and restores the snapshot/source backup.

## Failure handling

- Pipeline exceptions set the in-memory session to `error` and attempt to persist `recovery_failed`.
- Audit-write failures are logged into session events and not silently swallowed.
- Apply failures restore session state to `awaiting_approval` and record `recovery_failed`.
- Invalid approval and undo states record rejected audit events.
- Recovery-engine conflicts, invalid plans, unsafe schemas, and simulation failures create rolled-back `recovery_runs` records where the plan can be represented.
- A failed SQLite audit write raises rather than reporting success.

## Read and write behavior

Python read/write interfaces:

```python
from timetravel import audit

# Inside a database connection
audit.record_event(conn, "INC-12ABC3", "recovery_completed", "completed", {"code_patched": True})
events = audit.read_session_events(conn, "INC-12ABC3")
```

HTTP read interface:

```text
GET /api/session/INC-12ABC3/audit
```

## Transaction and consistency limits

- Session audit events are separate SQLite writes and are not an external immutable ledger.
- Recovery-engine steps, recovery run status, and recovery actions are written on the same SQLite connection but use explicit transaction boundaries appropriate to the engine.
- A database recovery and a source-code patch are not distributed-atomically committed.
- Undo restores a pre-recovery database snapshot and source backup; it does not guarantee external-system rollback.
- Process restart loses in-memory sessions but does not delete SQLite audit records.

## Reopening verification

Audit records must remain readable after closing and reopening `data/live.db` or an isolated temporary SQLite database. The test suite verifies this with `test_audit.py`.

## Demo reset behavior

The demo reset endpoint clears in-memory sessions and rebuilds the database schema. It removes `session_audit_events`, so audit history for reset demo sessions is not preserved across reset.

## SSE delivery relationship

SSE does not create duplicate audit storage. It reads `session_audit_events` and uses each row's SQLite `id` as both the SSE `id` and replay cursor. The stream is session-scoped and supports `Last-Event-ID` or `last_event_id` replay.

SSE delivery is at-least-once for persisted audit history. It does not claim exactly-once delivery; clients must deduplicate stable event IDs. Live events are readable only after they are persisted as audit rows.

The stream sends 15-second heartbeat comments and closes after a bounded 300-second window. It does not hold a SQLite transaction open. The HTTP handler checks client disconnects and stops the iterator promptly; the iterator also accepts a `closed` callback for direct callers and tests.

## Dashboard visualization contract

The Phase 4 dashboard reads only backend-provided session and audit data. It does not calculate a separate recovery plan in the browser.

- `recovery_preview` is built when the session reaches `awaiting_approval` by reading the merge plan and live database state without writes. It is labeled `PROPOSED — NOT APPLIED` until commit.
- `actual_recovery` is captured inside the apply database lock after commit and contains only values that can be read from the live database. Missing sampled rows are marked unavailable.
- `verification` is derived from post-apply smoke checks recorded by the engine. `unavailable` means no checks were executed; checksum verification is explicitly unavailable on the HTTP path even though it exists in the separate recovery package.
- `undo_state` is derived from backend undo calls and does not claim availability before a successful apply.

Projection rows are a bounded sample (20 rows in the backend default); `row_count`, `operation_counts`, and per-table counts cover the full plan. The HTTP recovery path produces no DELETE statements, so the projection reports `DELETE: 0` rather than rendering fabricated deletions. The renderer supports backend-supplied DELETE rows if a future backend exposes them.

The dashboard merges SSE lifecycle events and audit polling fallback by stable audit event ID. Duplicate IDs are ignored, polling is used only as a fallback, and no progress percentage is displayed because the backend does not emit completion ratios. All untrusted values are rendered with DOM text nodes; `recovery_view.js` never uses `innerHTML`.

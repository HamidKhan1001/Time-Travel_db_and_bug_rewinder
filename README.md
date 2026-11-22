# Time-Travel DB & Bug Rewinder

A local SQLite demonstration of recovering a corrupted database without losing legitimate writes made after the crash.

The demo intentionally runs `UPDATE inventory SET stock = ?` without a `WHERE` clause, wiping stock for all 1,420 SKUs. Orders placed during the outage are preserved. The agent rewinds a clone, extracts post-crash writes, plans a merge, asks a human to approve, applies the recovery, verifies the result, and can undo the rewind.

This is a prototype. It is SQLite-only and does not implement PostgreSQL WAL decoding, AWS RDS PITR, distributed recovery, authentication/RBAC, or production-grade deployment.

## Quick start

Requirements:

- Python 3.9+ with SQLite JSON functions enabled (`json_object()`; SQLite 3.38+ is typical).
- No third-party packages are required for the core demo or tests.
- Optional Node.js is used only for the JavaScript UI unit tests.
- Optional Gemini/Bedrock LLM providers require separate packages and credentials; see [`docs/ai-setup.md`](docs/ai-setup.md).

```bash
python3 server.py
# open http://localhost:8000
```

Set `PORT` to change the local port. The server binds to `127.0.0.1` only.

For a clean seeded state:

```bash
python3 reset.py
```

`reset.py` deletes generated demo databases in `data/`, restores the intentionally buggy handler, and recreates the schema. Do not run it against data you want to keep.

## React frontend (`frontend/`)

`frontend/` contains a separate React + Vite + Tailwind CSS interface built from the Google Stitch designs (Console, Review & approve, Audit log). It sits alongside the existing `web/` dashboard (which stays at `/`) and talks to the same API.

It requires Node.js 20.19+ or 22.12+ and runs in two modes:

```bash
cd frontend
npm install
npm run dev        # mock data, no backend needed (good for design work)
npm run dev:live   # talks to the real server: run `python3 server.py` in another terminal
# open http://localhost:5173
```

In development, Vite forwards `/api` requests to `http://127.0.0.1:8000` (override with `API_PROXY_TARGET`). The server also sends CORS headers for `localhost`/`127.0.0.1` origins only.

To serve the React app from the Python server itself (one process, one port):

```bash
cd frontend && npm install && npm run build:live
cd .. && python3 server.py
# open http://localhost:8000/app/   (the original dashboard stays at http://localhost:8000/)
```

`frontend/src/services/backend.js` calls the API and `frontend/src/services/adapters.js` translates the backend JSON into the shapes the screens read. Details: [`frontend/docs/BACKEND_INTEGRATION.md`](frontend/docs/BACKEND_INTEGRATION.md). Frontend unit tests: `cd frontend && npm test`.

## Architecture and workflow

- `timetravel/db.py` installs row-level `changelog` triggers on the four registered business tables: `customers`, `inventory`, `orders`, and `order_items`. This is logical trigger capture, not SQLite WAL journaling.
- `timetravel/tools.py` implements rewind-on-clone, delta extraction, three-way merge planning, patch diagnosis, and atomic apply with snapshots and smoke checks.
- `timetravel/agent.py` orchestrates the session, enforces the human-in-the-loop approval gate, and exposes undo.
- `timetravel/guard.py` deterministically blocks dangerous SQL such as `DROP`, `TRUNCATE`, `ALTER`, and unscoped `UPDATE`/`DELETE` unless explicitly approved.
- `timetravel/recovery/` adds durable transaction history, deterministic recovery plans, FK-aware execution, conflict checks, and SHA-256 checksum verification over configured business-table rows.
- `web/index.html`, `web/js/recovery_data.js`, and `web/js/recovery_view.js` render the dashboard, proposed recovery projection, actual post-apply values, lifecycle status, verification state, and undo state.

Recovery sequence:

1. Detect the unscoped write from the query log.
2. Clone the live database and reverse changes to just before the crash.
3. Extract and merge legitimate post-crash orders.
4. Build a read-only recovery preview showing proposed values and risk.
5. Pause for human approval via `POST /api/session/<id>/approve`.
6. Apply atomically to the live database, optionally patch the handler source, and run smoke checks.
7. Show actual sampled values separately from proposed values.
8. Allow `POST /api/session/<id>/undo` to restore the pre-recovery database snapshot and source backup.

Proposed rows are labeled `PROPOSED — NOT APPLIED`. Actual values appear only after commit. HTTP checksum verification is unavailable; the HTTP path records smoke checks only. Durable session audit events are written to `session_audit_events` and streamed over SSE.

## Demonstration scenarios

### Scenario A — inventory stock wipe (agent HITL workflow)

Run from the dashboard:

1. Click **Reset demo**.
2. Click **Trigger warehouse sync** to wipe inventory.
3. Click **Place 3 orders**.
4. Run the prefilled time-travel prompt.
5. Review the projection, conflict, risk score, and patch diff.
6. Approve and inspect actual restored values, verification, audit history, and undo state.
7. Re-run the crash to show the patched handler touches one row, then optionally undo.

Headless equivalent in an isolated temporary copy:

```bash
TT_PACE=0 python3 tests/e2e_isolated.py
```

Do not run `tests/e2e.py` directly from the repository root when you need to preserve `data/` or `app/handlers.py`; it resets and patches repository state.

### Scenario B — orders status wipe (direct recovery-engine workflow)

This scenario is intentionally separate from the agent HITL flow. It uses the shared transaction logger, planner, integrity checks, and recovery engine directly. It does not call the HTTP approval gate.

```bash
tmpdir=$(mktemp -d)
python3 tests/setup_second_crash.py --dir "$tmpdir"
python3 tests/run_second_crash.py --dir "$tmpdir"
```

It changes four seeded orders with `UPDATE orders SET status = 'cancelled'`, inserts legitimate order `2005` afterward, reverses only the faulty transaction, and writes `second_crash_report.json`. See [`SECOND_CRASH_SCENARIO.md`](SECOND_CRASH_SCENARIO.md).

## Testing and CI

Core tests use only the Python standard library. Optional AI providers are not required for the test suite. Output paths below are local and do not overwrite preserved historical reports.

```bash
# Complete unittest discovery
TT_PACE=0 python3 tests/run_ci_suite.py --output test-reports/local-ci.json

# Guard unit and deterministic fuzz tests
python3 -m unittest tests.test_guard tests.test_guard_fuzz -v

# Recovery engine, integrity, audit, API, SSE, projection, and timing tests
python3 -m unittest discover -s tests -p "test_*.py"

# Projection and JavaScript UI tests
python3 -m unittest tests.test_recovery_projection tests.test_recovery_ui -v
node --test tests/js/recovery_ui.test.js

# Isolated headless demo
TT_PACE=0 python3 tests/e2e_isolated.py

# Lightweight benchmark smoke
python3 benchmarks/benchmark_recovery.py --datasets 1000 --iterations 1 --output test-reports/local-benchmark-smoke.json

# Reproducible multi-repetition benchmark with medians
python3 benchmarks/benchmark_recovery.py --datasets 1000 10000 --iterations 3 --output test-reports/local-benchmark-full.json
```

The fuzz suite uses a fixed seed (`20261122`) and never executes generated SQL. GitHub Actions runs the suite on Python 3.11 and 3.12, then explicit guard tests, isolated E2E, and a 1K-row benchmark smoke. See [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

Python compilation check:

```bash
python3 -m compileall -q benchmarks tests timetravel server.py final_recovery_demo.py reset.py
```

## Performance and integrity evidence

Local SQLite benchmark evidence is recorded in [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md) and [`BENCHMARK_REPORT.md`](BENCHMARK_REPORT.md). These are local measurements from specific machines and commits; they are not an SLA or a production guarantee.

Important scopes:

- `integrity_status: VERIFIED` means checksum verification matched for the configured `db.TABLES` business rows, not the entire database file, schema, audit tables, or metadata.
- HTTP/UI verification is limited to post-apply smoke checks; checksum status is reported as unavailable there.
- Windows RSS values of `0.0` mean unavailable measurement, not zero memory use.
- Timing values are monotonic diagnostics for one process and are not restored after restart.

## Documentation

- [HTTP API, SSE events, and session fields](API.md)
- [Audit persistence and recovery lifecycle](docs/AUDIT.md)
- [Performance and checksum scope](docs/PERFORMANCE.md)
- [Database recovery engine scope](DATABASE_ENGINE_README.md)
- [Database limitations](DATABASE_LIMITATIONS.md)
- [Second crash scenario](SECOND_CRASH_SCENARIO.md)
- [Production recovery architecture (prototype plus proposed design)](PRODUCTION_RECOVERY_ARCHITECTURE.md)
- [AI provider setup](docs/ai-setup.md)
- [Devlog (historical planning notes)](docs/devlog.md)

## Known limitations

- SQLite-only prototype; no PostgreSQL WAL decoding, AWS RDS PITR integration, or distributed recovery executor.
- Capture is limited to registered business tables and DML operations; DDL, unmanaged tables, metadata tables, and out-of-band writes are unsupported.
- No authentication or RBAC; the demo server is local-only.
- In-memory sessions are lost on process restart; SQLite audit records remain.
- Database recovery and source-code patching are separate operations, not a distributed atomic commit.
- The second crash scenario exercises the recovery engine directly and does not verify the HITL approval gate.
- SSE is local SQLite polling with stable audit IDs and at-least-once delivery, not an external pub/sub system.

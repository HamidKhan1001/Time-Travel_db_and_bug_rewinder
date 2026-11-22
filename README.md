# Time-Travel DB & Bug Rewinder

Zero dependencies (Python 3.9+ stdlib + SQLite). `python3 server.py` -> http://localhost:8000

## Demo (3 min)
1. `python3 reset.py` (also the "Reset demo" button) - clean seeded state, buggy code restored.
2. Show healthy storefront. Click **① Trigger warehouse sync** -> inventory wiped to 0.
3. **② Place 3 orders** -> #1041-#1043 (one oversells a limited item: the "drama" conflict).
4. **③ Run Time-Travel** with the pre-filled prompt (slider changes "N minutes ago").
5. Walk through the proposed recovery projection, merge table, conflict, risk score, and patch diff. **④ Approve & Go Live**.
6. After approval, inspect actual sampled values, verification status, and undo availability. **⑤ Re-run the crash action** -> touches 1 row. Optional: **Undo** to rewind the rewind.

Keep the crash within ~2 min of running step 4 or the guardrail snaps the rewind point to just before the crash (also a nice moment to show).

## How it works
- `db.py` row-level change log via triggers (our WAL/CDC stream) -> point-in-time rewind by reversing changes on a clone.
- `tools.py` the five tools: rewind_branch, extract_delta, plan_merge (3-way merge + FK/idempotency/oversell resolver + dry run), diagnose_and_patch (verified on a clone), apply_recovery (atomic, smoke-checked, undoable).
- `guard.py` deterministic SQL policy: DROP/TRUNCATE/ALTER and unscoped UPDATE/DELETE blocked without approval.
- `agent.py` orchestrator + HITL gate. `TT_PACE=0` removes the small pacing delay.
- `recovery_projection.py` builds a bounded, read-only proposed state/diff projection from the approved merge plan and live database state.
- `web/js/recovery_data.js` and `web/js/recovery_view.js` render the projection, lifecycle, verification, and undo panels with safe DOM APIs.
- `python3 tests/e2e.py` runs the full flow headless.

## Testing and CI

Core tests use only the Python standard library. Optional AI providers are not required for the test suite.

```bash
# Complete unittest discovery
TT_PACE=0 python tests/run_ci_suite.py --output test-reports/phase1-local.json

# Guard unit and deterministic fuzz tests
python -m unittest tests.test_guard tests.test_guard_fuzz -v

# Recovery and second-crash suites
python -m unittest tests.test_foreign_key_recovery tests.test_phase9_comprehensive tests.test_second_crash_scenario -v

# Phase 4 projection and dashboard tests (Node test is skipped when Node.js is unavailable)
python -m unittest tests.test_recovery_projection tests.test_recovery_ui -v
node --test tests/js/recovery_ui.test.js

# Headless demo in an isolated temporary copy
TT_PACE=0 python tests/e2e_isolated.py

# Lightweight benchmark smoke
python benchmarks/benchmark_recovery.py --datasets 1000 --iterations 1 --output test-reports/phase1-benchmark-smoke.json
```

The isolation runner copies `app`, `seed`, `timetravel`, `tests`, and `data` into a temporary directory before executing the E2E demo. It does not reset or modify `data/live.db` in the repository.

The dashboard projection is a bounded sample of the full plan; aggregate counts cover every planned row. It never invents post-apply values: proposed rows are labeled `PROPOSED — NOT APPLIED`, actual values appear only after commit, and checksum verification is shown as unavailable because the HTTP path records smoke checks only. Lifecycle events use SSE stable IDs with audit polling fallback; the client deduplicates by ID and does not display invented progress percentages.

The fuzz suite uses a fixed seed (`20261122`) and does not execute generated SQL. A failing fuzz case reports the generated input and guard result; rerun it through `tests.test_guard_fuzz` for a reproducible failure.

GitHub Actions runs the same complete suite on Python 3.11 and 3.12, followed by explicit guard testing, isolated E2E, and a 1K-row benchmark smoke. Historical test and benchmark reports include the commit/date context where applicable and must not be rewritten to imply newer verification.

## Documentation

- Complete HTTP API and SSE stream: [`API.md`](API.md)
- Recovery and audit persistence lifecycle: [`docs/AUDIT.md`](docs/AUDIT.md)
- Database limitations: [`DATABASE_LIMITATIONS.md`](DATABASE_LIMITATIONS.md)
- AI provider setup: [`docs/ai-setup.md`](docs/ai-setup.md)

The core demo is SQLite-only. Optional Gemini and AWS Bedrock providers use structured fallback behavior; PostgreSQL WAL, RDS PITR, RBAC, SSE, and distributed production promotion are not implemented.

## Not in here yet
Intent parsing is regex, not an LLM; AWS (Bedrock/Strands/RDS PITR) is not wired. The tools are plain functions so wrapping them with Strands `@tool` is straightforward.

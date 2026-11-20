# Time-Travel DB & Bug Rewinder

Zero dependencies (Python 3.9+ stdlib + SQLite). `python3 server.py` -> http://localhost:8000

## Demo (3 min)
1. `python3 reset.py` (also the "Reset demo" button) - clean seeded state, buggy code restored.
2. Show healthy storefront. Click **① Trigger warehouse sync** -> inventory wiped to 0.
3. **② Place 3 orders** -> #1041-#1043 (one oversells a limited item: the "drama" conflict).
4. **③ Run Time-Travel** with the pre-filled prompt (slider changes "N minutes ago").
5. Walk through merge table, conflict, risk score, patch diff. **④ Approve & Go Live**.
6. **⑤ Re-run the crash action** -> touches 1 row. Optional: **Undo** to rewind the rewind.

Keep the crash within ~2 min of running step 4 or the guardrail snaps the rewind point to just before the crash (also a nice moment to show).

## How it works
- `db.py` row-level change log via triggers (our WAL/CDC stream) -> point-in-time rewind by reversing changes on a clone.
- `tools.py` the five tools: rewind_branch, extract_delta, plan_merge (3-way merge + FK/idempotency/oversell resolver + dry run), diagnose_and_patch (verified on a clone), apply_recovery (atomic, smoke-checked, undoable).
- `guard.py` deterministic SQL policy: DROP/TRUNCATE/ALTER and unscoped UPDATE/DELETE blocked without approval.
- `agent.py` orchestrator + HITL gate. `TT_PACE=0` removes the small pacing delay.
- `python3 tests/e2e.py` runs the full flow headless.

## Not in here yet
Intent parsing is regex, not an LLM; AWS (Bedrock/Strands/RDS PITR) is not wired. The tools are plain functions so wrapping them with Strands `@tool` is straightforward.

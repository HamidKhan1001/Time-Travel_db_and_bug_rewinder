# 0008. The legacy `changelog` stays until the rewind path moves to `transaction_history`

**Status:** accepted (revisit).

## Context
Two change-capture systems exist. `transaction_history` (durable, transaction-grouped, checksummed) powers the recovery engine and its audit trail. The older `changelog` (one row per trigger firing, timestamp ordered) is still read by:

- `tools.rewind_branch_tool` via `db.changes_after` / `db.reverse_changes` (time-based rewind of a clone),
- the stale-plan guard in `apply_recovery_tool` (`db.last_change_id`),
- the dashboard's event counter.

Two systems are a maintenance cost and a source of drift, so retiring `changelog` is desirable.

## Decision
Do not remove it yet. Rewinding by timestamp and the stale-plan marker are part of the safety story, and re-implementing them on `transaction_history` changes the most safety-critical path in the repository. Instead the legacy table was bounded (`TT_CHANGELOG_MAX_ROWS` pruning, an index on `ts`, O(1) marker) and `tools.py` now has characterization tests around exactly these call sites.

## Exit criteria
1. `rewind_branch_tool` reverses by `transaction_history` event ids and produces an identical clone (golden test against the current output).
2. The stale-plan marker uses `transaction_history`'s latest event id; a test proves a concurrent write still invalidates a plan.
3. Nothing reads `changelog`; then drop the triggers, the table and `prune_changelog`.

## Consequences
Until then both tables are written on every change (extra write cost and storage), and `changelog` pruning limits how far back a time-based rewind can reach.

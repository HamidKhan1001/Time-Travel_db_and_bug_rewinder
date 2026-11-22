# 0002. Rewind and test on a clone, never on production

**Status:** accepted.

## Context
An agent that rewinds production directly turns one incident into two if its plan is wrong, and gives a human nothing to review before the damage is done.

## Decision
Every step before approval runs on throwaway copies of the database. `rewind_branch` copies the live DB and reverses the change log on the copy. `plan_merge` does a three-way merge (rewound base, broken live, new writes) and dry-runs the result on another clone with integrity checks (foreign keys, no negative stock, idempotency keys, ID collisions). The patch is run against tests on a clone. Production is written once, in `apply_recovery`, inside one transaction.

## Consequences
- A failed or abandoned run cannot damage production. Discarding a plan leaves no trace on the data.
- The reviewer sees the exact result that will be applied, plus a risk score, instead of an intention.
- Cloning costs time and disk. At the benchmarked sizes this is fine; a large production database would need copy-on-write snapshots (the RDS PITR / storage-snapshot idea).
- The live DB can change between planning and approval. `apply_recovery` records a live marker and re-checks it, and a failed apply rolls back and returns the session to `awaiting_approval`.

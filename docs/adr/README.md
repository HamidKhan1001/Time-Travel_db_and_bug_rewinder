# Architecture decision records

Short notes on why the system is built the way it is. Format: context, decision, consequences. Add a new numbered file when you change one of these or make a comparable decision, and mark the old one superseded rather than editing history.

| # | Decision | Status |
|---|---|---|
| [0001](0001-trigger-based-change-capture.md) | Capture changes with triggers, not by reading the WAL | Accepted (prototype) |
| [0002](0002-rewind-on-a-clone.md) | Rewind and test on a clone, never on production | Accepted |
| [0003](0003-llm-proposes-code-verifies.md) | The LLM proposes; deterministic code verifies | Accepted |
| [0004](0004-human-approval-and-undo.md) | A human approves every apply, and every apply can be undone | Accepted |
| [0005](0005-ui-polls-through-adapters.md) | The UI polls the session and reads the API through adapters | Accepted |
| [0006](0006-standard-library-core.md) | The core engine uses only the standard library and SQLite | Accepted |
| [0007](0007-web-layer-structure.md) | The HTTP layer is a package with an explicit context and a route table | Accepted |
| [0008](0008-keep-the-legacy-changelog-for-now.md) | The legacy `changelog` stays until the rewind path moves to `transaction_history` | Accepted (revisit) |

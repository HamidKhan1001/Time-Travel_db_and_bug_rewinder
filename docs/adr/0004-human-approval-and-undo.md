# 0004. A human approves every apply, and every apply can be undone

**Status:** accepted.

## Context
Recovery touches the most sensitive thing a company has. Even a verified plan can be wrong in ways the checks do not cover (a business rule, an order that should be refunded rather than backordered).

## Decision
The session cannot reach `applying` except from `awaiting_approval`, and only an explicit `POST /api/session/<id>/approve` moves it there. `discard` rejects a plan without touching data. Before applying, a snapshot of the database and the original source file is written; `undo` restores both. The audit log records initiation, preview, approval, execution, verification, completion and undo, and survives an undo.

## Consequences
- No autonomous production change, at the cost of a human in the loop during an incident. The review screen is designed to make that review fast: merge decisions with reasons, the conflict, the risk score, the diff.
- Undo restores the whole database snapshot, so writes made after the apply are also lost on undo. It is a rewind of the rewind, not a surgical revert.
- Database restore and source-code restore are two operations, not one distributed transaction. A failure between them is handled (audit rows are preserved and `undo_failed` is recorded) but leaves a state a human must inspect.
- Approval is enforced by in-memory session state. There are no user identities yet, so the audit log cannot say *who* approved; see [SECURITY.md](../../SECURITY.md).

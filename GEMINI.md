# Time-Travel DB & Bug Rewinder — Project Context

## ⚡ Read this first

This is a hackathon project. **Submission deadline: 2026-12-12.**

The full devlog with codebase analysis, PRD summary, task breakdown, and build
plan is at:

```
docs/devlog.md
```

**Always read that file at the start of every conversation before doing anything.**

---

## What this project does

An AI agent that recovers corrupted production databases without losing
legitimate new data. When a bad deploy wipes inventory:

1. Rewinds a **clone** of the DB to just before the crash
2. Extracts every legitimate write made after the crash
3. Merges those writes back (3-way merge with FK/idempotency/oversell checks)
4. Diagnoses the buggy code, proposes a patch, verifies on the clone
5. Applies atomically — only after a **human approves**

## Stack

- Zero external dependencies: Python 3.9+ stdlib + SQLite only
- `python server.py` → http://localhost:8000
- `python reset.py` → clean demo state (~0.3s)
- `python tests/e2e.py` → full headless end-to-end test

## Key files

| File | What it is |
|------|-----------|
| `timetravel/agent.py` | Orchestrator, intent parsing, HITL gate, approve/undo |
| `timetravel/tools.py` | The 5 agent tools (all deterministic) |
| `timetravel/db.py` | SQLite schema, CDC triggers, clone, rewind |
| `timetravel/guard.py` | SQL safety guardrails (deterministic, LLM-proof) |
| `timetravel/seed.py` | Demo seed: 1,420 SKUs, 12 customers, 40 orders |
| `app/handlers.py` | Live app code the agent can patch (intentionally buggy) |
| `server.py` | HTTP server + all API routes |
| `web/index.html` | Single-file dark-mode SPA |
| `tests/e2e.py` | Headless end-to-end test |

## Safety rules (never violate)

- Nothing writes to production without human approval
- All rewinds / merges / patch tests run on a **clone**
- `guard.py` is deterministic — the LLM cannot override it
- Every apply is undoable

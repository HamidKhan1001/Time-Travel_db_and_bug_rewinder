# Devlog — Time-Travel DB & Bug Rewinder
> Last updated: 2026-11-22 · Submission deadline: 2026-12-12

---

## What This Project Is

**Time-Travel DB & Bug Rewinder** — a hackathon project that recovers corrupted production databases without losing legitimate new data, and without a full restore.

The core insight: when a bad deploy wipes data, you don't want to restore a backup (you lose new orders/signups). Instead, an AI agent:
1. Rewinds a **clone** of the DB to just before the crash
2. Extracts every legitimate write made after that point
3. Merges those writes back onto the rewound state
4. Diagnoses the buggy code, proposes a patch, verifies it on the clone
5. Applies everything atomically — only after a human approves

**Demo scenario:** Warehouse sync endpoint calls `UPDATE inventory SET stock = ?` with no WHERE clause → wipes all 1,420 SKUs to 0. Three orders arrive while everything is down. The agent recovers inventory, keeps the orders, patches the bug, and proves it in < 60 seconds.

---

## Repo Location
```
c:\Github Repos\Time-Travel_db_and_bug_rewinder\
```

## Stack
- **Zero external dependencies** — Python 3.9+ stdlib + SQLite only
- `python server.py` → http://localhost:8000
- `python reset.py` → clean demo state in ~0.3s
- `python tests/e2e.py` → full headless end-to-end test

---

## File Map

```
server.py                   HTTP server (stdlib only), all API routes
reset.py                    3-line reset script: calls seed.reset()
app/
  handlers.py               Live application code the agent can patch
                            (buggy: sync_stock has no WHERE clause)
seed/
  handlers_buggy.py.txt     Pristine copy of the buggy handler (reset source of truth)
timetravel/
  db.py                     SQLite layer: schema, CDC triggers, clone, rewind
  tools.py                  The 5 agent tools (all deterministic)
  agent.py                  Orchestrator: pipeline, HITL gate, approve, undo
  guard.py                  Deterministic SQL safety guardrails
  seed.py                   Demo seed: 1,420 SKUs, 12 customers, 40 orders
  appcode.py                Hot-reload of handlers.py (patch/undo take effect instantly)
  __init__.py
web/
  index.html                Single-file dark-mode SPA (~129 lines)
tests/
  e2e.py                    Headless end-to-end test (33 lines, passes)
data/
  .gitkeep                  live.db and branch files go here at runtime
```

---

## What's Already Built & Working

### Core Pipeline (all in `timetravel/tools.py`)
| Tool | What it does | Status |
|------|-------------|--------|
| `rewind_branch_tool` | Clones DB, reverses changelog events newest-first onto clone | ✅ Working |
| `extract_delta_tool` | Pulls orders/items/customers created after target_ts, labels pre/post-crash | ✅ Working |
| `plan_merge_tool` | 3-way merge: FK checks, idempotency dedup, oversell detection, dry-run on scratch clone, risk scoring (0–100) | ✅ Working |
| `diagnose_and_patch_tool` | Reads query_log, finds unscoped UPDATE, regex-patches source, verifies on sandbox clone with 2 tests | ✅ Working (regex only) |
| `apply_recovery_tool` | Atomic cutover: stale-plan check, pre-backup snapshot, smoke checks, rollback on failure | ✅ Working |

### Infrastructure
| Component | File | Status |
|-----------|------|--------|
| Row-level CDC via SQLite triggers | `db.py:62-71` | ✅ All 4 tables (I/U/D ops → `changelog`) |
| Controllable clock for seeding | `db.py:17-25` | ✅ Backdates history deterministically |
| SQL guard | `guard.py` | ✅ Blocks DROP/TRUNCATE/ALTER/unscoped UPDATE/DELETE. Deterministic — LLM cannot override |
| Orchestrator + HITL gate | `agent.py` | ✅ Phases: parsing → branching → extracting_delta → planning → diagnosing → awaiting_approval → applying → applied/undone |
| Approve + Undo | `agent.py:173`, `200` | ✅ Both wired end-to-end |
| Session streaming (polling) | `server.py:97`, `index.html:127` | ⚠️ Polls every 500ms — not true SSE yet |
| `TT_PACE` env var | `agent.py:10` | ✅ Controls animation speed (default 0.4s per step) |
| Web UI | `web/index.html` | ✅ Timeline, feed, merge table, diff viewer, approve/undo |
| E2E test | `tests/e2e.py` | ✅ Passes. Covers full flow including undo |
| Reset | `reset.py` | ✅ < 0.5s, restores buggy handler, cleans data/ |

### Known Bugs / Limitations (by design for demo)
- `app/handlers.py::sync_stock` — `UPDATE inventory SET stock = ?` with no WHERE clause (the intentional bug)
- `seed/handlers_buggy.py.txt` — identical buggy file, used as reset source

---

## What Does NOT Exist Yet

### Team 1 — Frontend
| Item | Gap | Effort |
|------|-----|--------|
| `ALERT BANNER` | `#inc` badge exists but too small; needs large animated alert | Small |
| `TIME TRAVEL UI` | Slider exists but doesn't replay inventory state; needs `GET /api/state?at=<ts>` | Medium |
| `DIFF VIEW` | No 3-column Before/After/Recovered table | Medium |
| `IMPACT METRICS` | Numbers exist in small cells; need large bold counter strip | Small |
| `LIVE STREAM` | Polling → SSE `EventSource` (depends on backend SSE endpoint) | Small |
| `HUMAN-IN-THE-LOOP` | Approve button + risk badge need to be visually paired | Small |
| `STAGE VISIBILITY` | No projector mode (large fonts, high contrast, `?projector` param) | Small |

### Team 2 — Backend

> Historical planning snapshot: the gaps in this section describe the state when the devlog was written. `SPEED PROOF`, `SCALE PROOF`, and `INTEGRITY` were addressed in later phases; current evidence is in [`PERFORMANCE.md`](PERFORMANCE.md) and [`AUDIT.md`](AUDIT.md).

| Item | Gap | Effort |
|------|-----|--------|
| `REAL-TIME` | No SSE endpoint. Add `GET /api/session/<id>/stream` → `text/event-stream` | Medium |
| `COMPLIANCE` | No audit log. Add `audit_log` table to schema; write row on session end | Small |
| `SPEED PROOF` | No elapsed time tracking. Add `started_at` to Session, surface `elapsed_ms` | Tiny |
| `API CONTRACT` | No `API.md` documenting routes/shapes | Tiny |

### Team 3 — Database
| Item | Gap | Effort |
|------|-----|--------|
| `VERSATILITY` | Only one crash scenario. Need second: e.g. `UPDATE inventory SET price_cents = ?` (price wipe) | Small |
| `SCALE PROOF` | No benchmark. Need `tests/bench.py` with 100k SKUs | Small |
| `INTEGRITY` | No checksum of rewound state vs pre-crash snapshot | Small |
| `PRODUCTION PATH` | No Postgres WAL / RDS PITR PoC or architecture doc | Medium |
| `CREDIBILITY` | Known limits section in README only has 2 lines | Tiny |

### Team 4 — AI (COMPLETED ✅ 2026-11-22)
| Item | Status | Implementation |
|------|--------|----------------|
| `TOOL CALLING` | ✅ Done | `timetravel/llm` package with Gemini and Bedrock structured output; regex fallback |
| `ROOT CAUSE` | ✅ Done | LLM proposes surgical code patch, verified on shadow clone with automatic regex fallback |
| `EXPLAINABILITY` | ✅ Done | Parallel LLM calls in `plan_merge_tool` attach plain-English `reason` per conflict |
| `GUARDRAIL` | ✅ Done | Intent parsing returns `confidence: 0–1`; auto-escalation warning logged if < 0.7 |
| `ZERO-CRASH FALLBACK` | ✅ Done | 100% test pass without any API key or external libraries installed; zero crash guarantee |
| `SPONSOR PRIZE` | ✅ Done | AWS Bedrock provider implemented using Claude 3 Haiku Tool Use |

### Team 5 — QA
| Item | Gap | Effort |
|------|-----|--------|
| `SQL FIREWALL` | No unit tests for guard. Need `tests/test_guard.py` | Small |
| `FUZZ TESTING` | No fuzz suite. Need 50+ nasty queries (mixed case, semicolons, Unicode, comments) | Small |
| `EDGE CASE` | Snap-to-crash guardrail tested implicitly; needs explicit unit test | Tiny |
| `CI GATE` | No GitHub Actions. Need `.github/workflows/ci.yml` running `e2e.py` on push | Small |
| `SPONSOR PRIZE` | No AWS Bedrock/Strands wiring | Medium |

---

## API Reference (current)

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Serves `web/index.html` |
| GET | `/api/state` | Live DB stats: inventory, orders, incident, warm branch, order dots |
| GET | `/api/session/<id>` | Full session JSON (phase, events, plan, patch, result) |
| POST | `/api/rewind` | `{prompt: str}` → starts agent, returns `{id: "INC-XXXXXX"}` |
| POST | `/api/session/<id>/approve` | Approves pending session, returns session JSON |
| POST | `/api/session/<id>/undo` | Undoes applied session, returns session JSON |
| POST | `/api/demo/reset` | Clears sessions, calls `seed.reset()` |
| POST | `/api/demo/crash` | Triggers the buggy sync_stock (wipes all inventory) |
| POST | `/api/demo/orders` | Places 3 demo orders (#1041–#1043) |

### Session JSON shape
```json
{
  "id": "INC-XXXXXX",
  "prompt": "...",
  "phase": "awaiting_approval | applied | undone | error | ...",
  "events": [{"t": float, "agent": str, "msg": str, "level": "info|warn|ok|error|gate"}],
  "parsed": {"rewind_seconds": float, "before_incident": bool, "preserve": [], "remediate": bool, "target_ts": float, "incident_ts": float},
  "branch": {"events_reversed": int, "inventory_rows": int, "units": int, "ms": float},
  "timeline": {"target": float, "incident": float, "now": float},
  "delta": {"orders": [...], "post_crash": int, "pre_crash": int},
  "plan": {"restored_rows": int, "orders_preserved": int, "conflicts": [...], "dry_run_ok": bool, "risk": {"score": int, "label": str, "factors": [...]}, "preview_sql": [...], "guardrails": [...]},
  "patch": {"found": bool, "explanation": str, "diff": str, "tests": [...], "patch_ok": bool},
  "result": {"checks": [...], "code_patched": bool},
  "can_approve": bool,
  "can_undo": bool
}
```

---

## Demo Script (5 steps, ~3 min)
1. `python reset.py` → show healthy storefront
2. **① Trigger warehouse sync** → all inventory → 0 (incident badge turns red)
3. **② Place 3 orders** → #1041–#1043 (one oversells limited APX-0777)
4. **③ Run Time-Travel** with the pre-filled prompt → watch agent feed
5. Review merge table, conflict (oversell), risk score, patch diff → **④ Approve & Go Live**
6. **⑤ Re-run crash action** → touches 1 row (bug patched). Optional: **Undo**

---

## Key Design Decisions

- **Zero external deps** — everything runs on stdlib + SQLite. Intentional for portability.
- **LLM cannot override the guard** — `guard.py` is called deterministically before every SQL statement. The LLM proposes, the system enforces.
- **Clone-first always** — rewinds, merges, patch tests all run on a branch. Production is never touched until human approval.
- **Stale-plan check** — `apply_recovery_tool` reads `MAX(id) FROM changelog` at plan time and again at apply time. If live data changed, it refuses and asks for a re-run.
- **Hot-reload patching** — `appcode.py` compiles `handlers.py` with `exec()` so a code patch takes effect instantly without restarting the server.

---

## Suggested Build Order (3 weeks to Dec 12)

### Week 1 (Nov 22–29): Core Features
- API contract doc (`API.md`)
- LLM intent parsing + regex fallback (`agent.py`)
- LLM patch proposal + keep existing clone verification (`tools.py`)
- Second crash scenario — price wipe (`handlers.py`, `seed.py`, `server.py`)
- Guard unit tests + fuzz suite (`tests/test_guard.py`)
- SSE streaming backend (`server.py`)
- Audit log (`db.py`, `agent.py`)

### Week 2 (Nov 30–Dec 7): Polish & Hardening
- SSE client in UI (`index.html`)
- 3-column diff view + impact metrics strip (`index.html`)
- Projector mode (`index.html`)
- Alert banner polish
- Confidence score + auto-escalation (`agent.py`)
- Plain-language merge reasons (`tools.py`)
- Integrity checksum in rewind (`tools.py`)
- Benchmark script 100k rows (`tests/bench.py`)
- CI GitHub Actions (`.github/workflows/ci.yml`)
- Speed metric (elapsed_ms in session)

### Week 3 (Dec 8–12): AWS + Rehearsal
- AWS Bedrock / Strands wiring
- RDS PITR architecture doc
- Known limits + production path docs
- 5× full rehearsals (one chaos run)
- Record backup video
- Submission

---

## Open Questions
1. **Which LLM provider?** Gemini API (already available via this environment), AWS Bedrock (needed for sponsor prize), or both with a config switch?
2. **Team roles?** Who owns which numbered team area?
3. **Second crash scenario** — price wipe confirmed, or different idea?

---

## Hammad Work — Task 3 (Database Recovery Engine)

Hammad's Task 3 contribution (commit `758298d`) added the production recovery engine,
benchmarks, second crash scenario, integrity verification, and architecture docs.
It was originally pushed directly to `main`; this PR exists so the work can be
reviewed explicitly.

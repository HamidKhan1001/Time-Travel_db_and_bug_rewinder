# Devlog — Time-Travel DB & Bug Rewinder
> Historical planning and phase notes. Several entries describe earlier project states and are superseded by [`README.md`](../README.md), [`API.md`](../API.md), [`PERFORMANCE.md`](PERFORMANCE.md), [`AUDIT.md`](AUDIT.md), and [`DATABASE_LIMITATIONS.md`](DATABASE_LIMITATIONS.md). Do not read the gap lists below as current status.
>
> Last updated: 2026-11-22 (latest entry at the bottom) · Submission deadline: 2026-12-12

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
| Session streaming (polling) | `server.py`, `index.html` | Historical: polling at this point; SSE was added later at `/api/session/<id>/events` |
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

---

## 2026-11-22: Frontend-backend integration, quality gate, repo structure (PRs #8 and #9)

**Integration**
- React UI now talks to the real server. `npm run dev` = mocks, `npm run dev:live` = real API. `frontend/src/services/adapters.js` turns backend JSON into the shapes the screens read (pure, unit-tested).
- `server.py` serves the built UI at `/app/`; `/` redirects there. The legacy `web/` dashboard and its tests were removed.
- New API: `GET /api/audit`, `/api/audit/summary`, `/api/audit/<id>`, `POST /api/session/<id>/discard`, `GET /api/health`. Every response has `X-Request-Id`; requests are logged. Optional bearer token via `TT_API_TOKEN`; `HOST` is configurable.
- `docs/openapi.json` plus a contract test that fails if the spec and `server.py` disagree.

**Bugs found by testing the real flow (all fixed, each with a regression test)**
- Undo restored an old DB snapshot and erased the session's audit events. Audit rows are now re-inserted, even if the code restore fails.
- `/api/state` always reported `patched: true` because `place_order()` contains `WHERE sku = ?`.
- Approve was enabled when the merge dry run failed but the patch tests passed.
- A failed apply (plan still actionable) was shown as a terminal failure in the audit log.
- The console's pre-filled prompt could not be parsed by the rule-based parser, so the first demo click failed. Parser now accepts "prior to the sync" phrasing; default prompt changed to one that rewinds, keeps orders and fixes the bug.
- Any `KeyError` in a POST handler was reported as `404 unknown route`; a missing field is now `400`.
- A web page on another origin could POST to the local API (for example `/api/demo/reset`); non-local origins now get 403.
- Smaller: double-click on Discard, incident banner after a rewind-only recovery, errored runs showing every step done.

**Quality gate (CI)**
- ruff, mypy (26 files clean), Python tests on 3.11 and 3.12 with a coverage floor of 75% (measured 81%), intent evals, ESLint, frontend unit tests, Playwright end-to-end, Docker build and health check, `pip-audit` and `npm audit`, then one **Quality gate** job.
- Playwright drives the real UI against the real server: crash, rewind, approve, patched re-run (touches 1 row), audit log, undo, discard.
- `hamid_bot` (`.github/workflows/hamid_bot.yml`, reusable) approves low-risk PRs after the gate. It never approves forks, drafts, Dependabot, or changes to `.github/`, `timetravel/guard.py`, `pyproject.toml`, `requirements*.txt`, `frontend/package*.json`. Verified on GitHub: declined on a PR touching `.github/`, approved a docs-only test PR once the repo setting "Allow GitHub Actions to create and approve pull requests" was on.

**AI evals**
- `evals/` holds 24 hand-labelled prompts. The rule-based parser gets 16/24: perfect on plain phrasing and units, 1/7 on paraphrases ("half an hour ago", "preserve the orders", "do not fix anything"). `baseline.json` makes regressions fail. The live-LLM path has not been scored; run `python3 evals/run_evals.py --llm` with a key.

**Structure and docs**
- Analysis docs, benchmark evidence (`test-reports/` -> `docs/evidence/`), PRD and the CLI demo moved out of the repo root. Five requirements files replaced by `pyproject.toml` extras (`gemini`, `bedrock`, `ai`, `dev`).
- Added Dockerfile and compose (non-root, health check, loopback-only port), `docs/ARCHITECTURE.md` with diagrams, six ADRs in `docs/adr/`, CONTRIBUTING, SECURITY, CHANGELOG, CODEOWNERS, Dependabot, PR template. README rewritten.
- Repo description and topics set on GitHub.

**Process notes**
- PR #8 was merged after its first commit only, so later commits pushed to that branch were not in `main` and CI never ran on them. They were re-submitted in PR #9. Check `gh pr view <n> --json state` before pushing more to a PR branch.
- One full-suite run once showed 2 failures that did not recur in the 6+ full runs after it; cause not identified.

**Still open**
- Score the live LLM path with a real key (Gemini or Bedrock).
- PostgreSQL logical decoding / RDS point-in-time recovery spike (documented as proposed only).
- Show `recovery_preview`, `actual_recovery` and `verification` in the React screens (the old dashboard did; the API still returns them).
- Second crash scenario is not reachable from the UI.
- Require the Quality gate check in branch protection for `main`.
- Sessions are in memory; no per-user identity, so the audit log cannot say who approved.

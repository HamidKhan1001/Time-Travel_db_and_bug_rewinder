# Database Architecture Analysis — Task 3: Database Engine

> **Historical snapshot.** This document describes the repository at an earlier commit and includes earlier file counts, environments, and planned work. Current implementation status is in [`README.md`](README.md), [`API.md`](API.md), [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md), [`DATABASE_ENGINE_README.md`](DATABASE_ENGINE_README.md), [`DATABASE_LIMITATIONS.md`](DATABASE_LIMITATIONS.md), and [`PRODUCTION_RECOVERY_ARCHITECTURE.md`](PRODUCTION_RECOVERY_ARCHITECTURE.md).
>
> Current corrections to this snapshot: the agent is LLM-first with deterministic fallback; requirements files and GitHub Actions CI exist; SSE is implemented; audit persistence exists; API contract documentation exists; recovery code lives in `timetravel/recovery/`.

Historical status at inspection: **Phase 1 analysis complete; Phases 2–7 recovery engine implementation and performance benchmarking complete. Phase 8 awaits approval.**
Historical repository inspected: 16 tracked files, one commit with substantive code (`5d1e083`), one initial commit (`b3c647f`).

---

## 1. Scope and method

I inspected every tracked file, including source, tests, frontend, seed fixtures, and configuration. I also ran the existing end-to-end test in an **isolated copy** outside the workspace so no repository file was modified. Baseline result: `E2E PASS`, with 1,434 reversed changelog events, 1,419 inventory rows restored, one oversell conflict, and `MEDIUM` risk score 25/100.

Verified runtime in this environment: Python 3.14.6, SQLite 3.53.2. The README declares Python 3.9+ stdlib + SQLite with no third-party dependencies.

No code, schema, API, test, or configuration file was changed while producing this document. The only new file is this analysis.

---

## 2. Existing project architecture

### 2.1 Repository layout

| Path | Role |
|---|---|
| `server.py` | Stdlib `ThreadingHTTPServer`; all HTTP routing, JSON state assembly, startup seeding, background branch warmer (`server.py:8-12`, `server.py:15-27`, `server.py:30-46`, `server.py:49-121`). |
| `app/handlers.py` | Storefront business logic loaded from source text at runtime; contains the intentional bug and the code target for patch/undo (`app/handlers.py:1-49`). |
| `seed/handlers_buggy.py.txt` | Pristine copy of the buggy handler restored by `seed.reset()` (`seed/handlers_buggy.py.txt:1-49`, `timetravel/seed.py:23`). |
| `timetravel/db.py` | SQLite connection setup, schema, CDC triggers, clone, compensation/reversal (`timetravel/db.py:1-101`). |
| `timetravel/tools.py` | The five deterministic recovery tools and incident detection (`timetravel/tools.py:1-289`). |
| `timetravel/agent.py` | Orchestration, regex intent parsing, HITL session state, event feed (`timetravel/agent.py:1-210`). |
| `timetravel/guard.py` | Regex SQL policy checks (`timetravel/guard.py:1-27`). |
| `timetravel/appcode.py` | Runtime source read/write/reload for the patchable handler (`timetravel/appcode.py:1-31`). |
| `timetravel/seed.py` | Deterministic demo fixture and reset (`timetravel/seed.py:1-67`). |
| `web/index.html` | Single-file dashboard; polls `/api/state` and `/api/session/{id}` (`web/index.html:67-129`). |
| `tests/e2e.py` | Single standalone assertion script (`tests/e2e.py:1-33`). |
| `reset.py` | CLI wrapper around `seed.reset()` (`reset.py:1-3`). |
| `data/.gitkeep` | Keeps the ignored runtime data directory in git. |

### 2.2 Request and control flow

```text
Browser (web/index.html)
  | fetch JSON
  v
server.py  ->  appcode.fn("place_order"/"sync_stock")  ->  app/handlers.py  ->  SQLite live.db
  |
  +-> agent.start(prompt) / approve(sid) / undo(sid)
        -> tools.py  ->  db.py  ->  snapshot / branch / scratch / backup DB files
        -> guard.py
        -> appcode.py (source patch + reload)

GET /api/state                  -> server.api_state() -> tools.detect_incident()
GET /api/session/{id}           -> agent.SESSIONS[id].to_json()
POST /api/rewind                -> agent.start(prompt)
POST /api/session/{id}/approve  -> agent.approve(id)
POST /api/session/{id}/undo     -> agent.undo(id)
```

Important: the "AI agent" is **not an external service**. It is an in-process Python orchestrator imported directly by `server.py:8`. It does not call backend HTTP APIs. `README.md:22-23` explicitly notes that intent parsing is regex, not an LLM, and that AWS/Bedrock/Strands are not wired. The only network JSON boundary is browser ↔ `server.py`.

### 2.3 Languages, frameworks, and dependencies

- Language: Python only. JavaScript/CSS are inline in the single HTML file.
- Web framework: none; `http.server` from the standard library.
- ORM: none. No SQLAlchemy, Django, Flask, FastAPI, Pydantic, or Alembic.
- Dependency files: none. No `requirements.txt`, `pyproject.toml`, `setup.cfg`, `pytest.ini`, `tox.ini`, Makefile, CI workflow, or `.env`.
- Runtime constraint: stdlib-only (`README.md:3`). Any Task 3 engine must remain stdlib-only unless explicitly approved.
- Hidden SQLite requirement: triggers use `json_object()` (`timetravel/db.py:64-71`), requiring SQLite 3.38+ with JSON support. `ON CONFLICT` UPSERT requires 3.24+ (`timetravel/tools.py:16-22`). `Connection.backup()` requires 3.7+ (`timetravel/db.py:79`).

---

## 3. Database technology

**Confirmed technology: SQLite**, accessed through Python's built-in `sqlite3`.

Evidence:

- `import sqlite3` and `sqlite3.connect(...)` in `timetravel/db.py:4,52`.
- Live database path `data/live.db`, derived from repository root (`timetravel/db.py:8-10`).
- SQLite pragmas and SQLite-specific SQL: `PRAGMA foreign_keys=ON`, `sqlite_sequence`, `AUTOINCREMENT`, `ON CONFLICT`, `json_object()`, `Connection.backup()` (`timetravel/db.py:51-71`, `timetravel/tools.py:16-22`, `timetravel/tools.py:79`).
- "WAL/CDC stream" in comments is a **logical row-level `changelog` implemented with triggers**, not SQLite WAL journaling (`timetravel/db.py:1,45-48,62-71`). No `PRAGMA journal_mode=WAL` is configured.

Connection contract (`timetravel/db.py:51-56`):

```python
sqlite3.connect(path, timeout=30, check_same_thread=False, isolation_level=None)
row_factory = sqlite3.Row
create_function("app_now", 0, clock.now)
PRAGMA foreign_keys=ON
```

Consequences:

- `isolation_level=None` means autocommit; all multi-statement atomicity is explicit.
- Callers use `row["column"]`; a plain `sqlite3.connect()` would break them.
- Triggers require the custom `app_now()` function; raw connections would fail.
- Foreign keys are enforced on every connection, including clones.
- `db.LOCK` is a process-local `threading.RLock` (`timetravel/db.py:11`), not a cross-process lock.

---

## 4. Current database schema

### 4.1 Schema definition

Defined as one SQL string in `timetravel/db.py:27-48`; there are **no model classes and no migration files**.

| Table | Columns | Constraints / keys |
|---|---|---|
| `customers` | `id INTEGER PRIMARY KEY`, `name TEXT NOT NULL`, `email TEXT NOT NULL` | Single-column PK. |
| `inventory` | `sku TEXT PRIMARY KEY`, `name TEXT NOT NULL`, `stock INTEGER NOT NULL`, `price_cents INTEGER NOT NULL` | `CHECK (stock >= 0)`. No check on price. |
| `orders` | `id INTEGER PRIMARY KEY AUTOINCREMENT`, `customer_id INTEGER NOT NULL`, `total_cents INTEGER NOT NULL`, `status TEXT NOT NULL`, `idem_key TEXT UNIQUE`, `created_at REAL NOT NULL` | FK `customer_id → customers.id`, default `NO ACTION`; nullable `idem_key`. |
| `order_items` | `id INTEGER PRIMARY KEY AUTOINCREMENT`, `order_id INTEGER NOT NULL`, `sku TEXT NOT NULL`, `qty INTEGER NOT NULL`, `unit_cents INTEGER NOT NULL` | FKs `order_id → orders.id` and `sku → inventory.sku`, default `NO ACTION`; no `qty > 0` check. |
| `query_log` | `id INTEGER PRIMARY KEY AUTOINCREMENT`, `ts REAL NOT NULL`, `source TEXT`, `sql TEXT`, `rows_affected INTEGER` | Observability only; no CDC trigger. |
| `changelog` | `id INTEGER PRIMARY KEY AUTOINCREMENT`, `ts REAL NOT NULL`, `tbl TEXT NOT NULL`, `op TEXT NOT NULL`, `pk` (untyped), `old TEXT`, `new TEXT` | Row-level CDC log; no self-trigger. |

`sqlite_sequence` is manually seeded with `('orders', 1000)` so the demo's first order is `#1001` (`timetravel/db.py:59-61`).

### 4.2 Relationships

```text
customers.id  ──1:N──>  orders.customer_id
orders.id     ──1:N──>  order_items.order_id
inventory.sku ──1:N──>  order_items.sku

query_log     no relationships
changelog     logical pointer only: (tbl, pk)
```

All foreign keys use implicit `NO ACTION`, so reversal order matters.

### 4.3 CDC implementation

`TABLES = {"customers": "id", "inventory": "sku", "orders": "id", "order_items": "id"}` is the single-column PK registry (`timetravel/db.py:13-14`). `create_schema()` generates 12 triggers from it (`timetravel/db.py:62-71`):

- `{table}_ai`: after INSERT → `changelog(..., op='I', pk=NEW.pk, old=NULL, new=json_object(NEW.*))`
- `{table}_au`: after UPDATE → `changelog(..., op='U', pk=NEW.pk, old=json_object(OLD.*), new=json_object(NEW.*))`
- `{table}_ad`: after DELETE → `changelog(..., op='D', pk=OLD.pk, old=json_object(OLD.*), new=NULL)`

`app_now()` is `time.time() + clock.offset` (`timetravel/db.py:17-25`). The seed manipulates the global offset to backdate history (`timetravel/seed.py:31,43,49`). `changes_after()` filters with strict `ts > ?` and orders by `id DESC` (`timetravel/db.py:100-101`).

### 4.4 Seed / demo data

- 12 customers; 1,420 SKUs; 40 historical orders `#1001–#1040` (`timetravel/seed.py:8-18,31-49`).
- Fixed SKUs include `APX-0007` stock 120 and `APX-0777` stock 2 (`timetravel/seed.py:10-16`).
- `demo_orders()` creates `#1041–#1043`; `#1043` orders 3 units of `APX-0777`, producing exactly one oversell conflict (`timetravel/seed.py:53-66`, `tests/e2e.py:19`).
- `seed.reset()` deletes all `data/*.db`, restores buggy source, recreates schema, and reseeds (`timetravel/seed.py:22-50`). It does **not** delete `data/backup_*.py` because its glob only matches `*.db`.

### 4.5 Runtime artifacts

| File | Purpose | Cleanup |
|---|---|---|
| `data/live.db` | Production/demo DB. | Deleted by `seed.reset()`. |
| `data/branch_{SID}.db` | Rewound branch. | Only reset; open connection retained in `agent.Session.internal` and never closed (`timetravel/agent.py:112-115`). |
| `data/scratch_{SID}.db` | Merge dry-run clone. | Removed on success; leaked if dry run raises (`timetravel/tools.py:153-159`). |
| `data/backup_{SID}.db` | Pre-cutover snapshot for undo. | Only reset (`timetravel/tools.py:265-266`). |
| `data/backup_{SID}.py` | Pre-cutover source for undo. | Not cleaned by reset (`timetravel/tools.py:267-268`). |

`.gitignore` ignores `data/*.db` and `data/*.py` (`.gitignore:1-2`). New artifacts with other extensions would be committed accidentally unless `.gitignore` and reset cleanup are updated.

---

## 5. Existing recovery implementation

### 5.1 Crash simulation

- UI button: `① Trigger warehouse sync (bug)` calls `POST /api/demo/crash` (`web/index.html:75`).
- Route: `POST /api/demo/crash` delegates to `POST /api/admin/sync-stock` with hardcoded `{"sku": "APX-0007", "stock": 0}` (`server.py:66-67`).
- Buggy handler ignores `sku` and runs `UPDATE inventory SET stock = ?` with no `WHERE` (`app/handlers.py:12-19`). This sets all 1,420 SKUs to zero.
- `run_sql()` records the SQL and `rowcount` in `query_log` (`app/handlers.py:5-9`). Direct writes elsewhere are CDC-logged but not query-logged.
- After a patch, the same payload updates exactly 1 row and missing `sku` raises `ValueError` (`timetravel/tools.py:210-212`, `tests/e2e.py:25-27`).

### 5.2 Change tracking / incident detection

- Row changes are tracked by the triggers in §4.3.
- Statement-level hints are tracked separately in `query_log`.
- `tools.detect_incident()` returns the newest `query_log` row with `rows_affected > 25` whose SQL fails `guard.analyze()` (`timetravel/tools.py:28-33`).
- `guard.analyze()` blocks multi-statement SQL, `DROP|TRUNCATE|ALTER|ATTACH|DETACH`, and unscoped `UPDATE`/`DELETE` unless explicitly approved (`timetravel/guard.py:4-23`).

### 5.3 The five tools

| Tool | Location | Behavior |
|---|---|---|
| `rewind_branch_tool` | `timetravel/tools.py:37-46` | Reads `changes_after(live, target_ts)`, clones live, calls `reverse_changes()`, returns open branch connection + stats. |
| `extract_delta_tool` | `timetravel/tools.py:50-63` | Selects orders with `created_at > target_ts`, their items, and their customers; annotates `phase` and `items`. |
| `plan_merge_tool` | `timetravel/tools.py:97-195` | Builds stock-only three-way plan from rewound base, broken live, and delta; checks FK, id collisions, idempotency keys, orphan SKU, oversell; dry-runs on a scratch clone; computes risk. |
| `diagnose_and_patch_tool` | `timetravel/tools.py:216-256` | Textually rewrites the exact `sql = "UPDATE inventory SET stock = ?"` line, verifies on in-memory clone of branch, produces diff. |
| `apply_recovery_tool` / `undo_recovery` | `timetravel/tools.py:260-289` | Stale marker check, backup, `BEGIN IMMEDIATE`, execute plan, smoke checks, commit, then source patch; undo restores DB snapshot and source. |

`db.reverse_changes()` (`timetravel/db.py:83-97`) inverts events newest-first: `I → DELETE`, `U → UPDATE ... SET old values`, `D → INSERT old row`. The `since_ts` argument is unused; correctness depends entirely on the caller filtering events.

### 5.4 Orchestration and HITL

`agent._pipeline()` (`timetravel/agent.py:82-170`) runs:

1. Parse prompt with regex (`timetravel/agent.py:19-34`).
2. Sn incident from `query_log`; snap rewind target to `incident.ts - 1` if requested target is after the crash (`timetravel/agent.py:89-108`).
3. Branch → delta → merge plan → optional diagnosis/patch (`timetravel/agent.py:110-163`).
4. Pause at `phase="awaiting_approval"` (`timetravel/agent.py:165-170`).
5. `approve()` applies the plan under `db.LOCK`; failure rolls back and returns to `awaiting_approval` (`timetravel/agent.py:173-197`).
6. `undo()` restores the pre-cutover snapshot and sets `phase="undone"` (`timetravel/agent.py:200-210`).

Sessions are in-memory only in `agent.SESSIONS` (`timetravel/agent.py:11,66`); a server restart loses them and their undo capability.

### 5.5 Backend APIs for recovery

Exact routes and payloads (`server.py:49-76,91-111`):

- `GET /api/state` → state object; no params.
- `GET /api/session/{id}` → full `Session.to_json()`.
- `POST /api/orders` → `{"customer_id", "idem_key"?, "items": [...]}`.
- `POST /api/admin/sync-stock` → `{"sku", "stock"}`.
- `POST /api/demo/reset` → `{"ok": true}`.
- `POST /api/demo/crash` → passthrough `{"updated_rows": int}`.
- `POST /api/demo/orders` → `{"orders": [...]}`.
- `POST /api/rewind` → `{"prompt": str}` → `{"id": "INC-XXXXXX"}`.
- `POST /api/session/{id}/approve` → session JSON.
- `POST /api/session/{id}/undo` → session JSON.
- Unknown POST → `404 {"error": "unknown route ..."}`; other POST errors → `400 {"error": str(e)}`. Unknown GET session → `500`.

### 5.6 Verification performed

The isolated run of `python3 tests/e2e.py` passed. Notable output:

- Incident: unscoped write touched 1,420 rows.
- Rewind: 1,434 events reversed; branch had 1,420 SKUs / 163,393 units.
- Delta: 3 post-crash orders `#1041–#1043`.
- Plan: 1,419 inventory rows restored; 3 orders preserved; 1 conflict; dry run passed.
- Risk: `MEDIUM` 25/100 (`8 + 12 + 5`).
- Post-cutover: 163,387 units; `#1043` = `backorder`; re-run crash touched 1 row; undo restored buggy behavior.

This confirms the current engine satisfies the single-script demo, but the implementation has the limitations below.

---

## 6. Missing database recovery capabilities

These are gaps relative to a general recovery engine, not necessarily demo blockers:

1. **No transaction-aware CDC.** Multi-statement `place_order` writes (`app/handlers.py:29-45`) are logged as independent events without a transaction ID. A `ts` threshold can split a logical transaction.
2. **Time/order mismatch.** Selection uses wall-clock `ts` with a mutable global offset, while undo order uses `changelog.id`. If the clock moves backward, later writes can be excluded while earlier ones are reversed (`timetravel/db.py:17-25,100-101`; `timetravel/seed.py:31,43,49`).
3. **PK changes are not reversible.** UPDATE triggers store `NEW.pk`, and `reverse_changes()` excludes the PK from the `SET` clause, so an old PK is never restored (`timetravel/db.py:69,86,91-93`). Composite keys are unsupported by design (`timetravel/db.py:13-14`).
4. **Compensation writes are re-logged.** `clone()` copies triggers via `sqlite3.Connection.backup()`; compensating statements append new `changelog` rows into the branch (`timetravel/db.py:74-80,83-97`). The branch is not a faithful point-in-time image.
5. **Merge is stock-only.** `plan_merge_tool()` restores `inventory.stock` only; `INV_UPSERT` never repairs corrupted `name` or `price_cents` (`timetravel/tools.py:16-17,142-143`). It is not a full row-level three-way merge across all four business tables.
6. **Some conflicts are detected but not resolved.** `id-collision`, `duplicate-idempotency-key`, and `orphan-sku` are reported, yet the offending rows remain in the plan and may be skipped by `ON CONFLICT DO NOTHING` or fail the dry run (`timetravel/tools.py:108-125,147-149`).
7. **Verification is shallow.** `run_checks()` checks FK validity, non-negative stock, stock equality, and order presence only (`timetravel/tools.py:67-81`). It does not verify full row content, totals, statuses, or absence of unexpected rows.
8. **No schema versioning or migrations.** `SCHEMA` is a static string; `create_schema()` assumes a fresh database (`timetravel/db.py:27-71`). Trigger JSON snapshots would silently miss later column changes.
9. **No durable session/plan persistence.** `SESSIONS` is in memory; plans contain live connections and tuple rows that are not serializable (`timetravel/agent.py:11,41,115`).
10. **No cross-process safety / strict stale-check.** Staleness is checked via `MAX(changelog.id)` before a snapshot and before `BEGIN IMMEDIATE`, leaving a TOCTOU window (`timetravel/tools.py:262-269`). `db.LOCK` only protects one process.
11. **Code and DB cutover are not atomic together.** The DB commits at `timetravel/tools.py:275`; source is written afterwards at `timetravel/tools.py:279-280`. A file-write failure leaves DB and code inconsistent.
12. **Artifact lifecycle is incomplete.** Branch connections are never closed; scratch files leak on exceptions; `backup_*.py` survives reset (`timetravel/agent.py:115`, `timetravel/tools.py:153-159,267-268`, `timetravel/seed.py:24-25`).
13. **No retention, compaction, or pruning of `changelog`/`query_log`.** The log grows indefinitely (`timetravel/db.py:45-48`).
14. **No managed backup catalog/restore verification.** Backups are per-session files with no metadata, checksum, retention, or validation.
15. **Incident detection is narrow.** It requires `rows_affected > 25` and relies on regex guard semantics; `guard.is_unscoped()` also returns true for destructive/multi-statement SQL, and `WHERE 1=1` is treated as scoped (`timetravel/tools.py:30-31`, `timetravel/guard.py:4-27`).
16. **No WAL journal mode / coordinated checkpointing.** The "WAL stream" is logical, not SQLite WAL; enabling real WAL would change clone/delete behavior and reset cleanup.

---

## 7. Files that will need modification

### 7.1 Strict non-invasive option (recommended for first implementation)

**No existing files need modification.** Add a new engine module and new tests. This satisfies Task 3 without changing any current contract.

### 7.2 Minimal integration option (only after approval)

| File | Change | Contract requirement |
|---|---|---|
| `timetravel/tools.py` | Optionally change the *internals* of `rewind_branch_tool`, `plan_merge_tool`, `apply_recovery_tool`, and `undo_recovery` to delegate to the new engine. | Keep every signature and return dictionary exactly as listed in §9. Do not change SQL statement constants or tuple ordering. |
| `timetravel/db.py` | Optionally add additive helpers/aliases for event selection by `id` and trigger-suppressed compensation. | Do not rename or change `BASE`, `DATA`, `LIVE`, `LOCK`, `TABLES`, `clock`, `SCHEMA`, `connect`, `create_schema`, `clone`, `reverse_changes`, or `changes_after`. |
| `server.py` | Only if engine diagnostics are required in the UI: add **new nested keys** to `api_state()`. | Never rename/remove existing keys; no new routes required. |
| `timetravel/agent.py` | Only if new session diagnostics are required: add **new keys** to `Session.to_json()`. | Do not change phase strings, `events` shape/order, or `can_approve`/`can_undo`. |
| `.gitignore` / `timetravel/seed.py` | Only if new artifacts use extensions other than `.db`/`.py`. | Prefer `.db` or `.py` filenames to avoid this entirely. |
| `README.md` | Optional documentation update after implementation. | Not needed for code correctness. |

### 7.3 Explicitly do not modify for Task 3

`web/index.html`, `app/handlers.py`, `seed/handlers_buggy.py.txt`, `tests/e2e.py`, `reset.py`, and all seed constants. `app/handlers.py` is dynamically executed and overwritten by demo patch/undo; exact SQL text is matched by `tools._patch_source()` (`timetravel/tools.py:199-213`).

---

## 8. New files that should be created

| File | Purpose |
|---|---|
| `timetravel/engine.py` | **Best location for the recovery engine.** Additive core with no framework, no ORM, no new dependency. Wraps `db.py` primitives and `guard.py`; called by current tool façades when integration is approved. |
| `tests/test_engine.py` | Standalone stdlib assertion script, following `tests/e2e.py` style. Must set `TT_PACE=0` before importing `timetravel` (`tests/e2e.py:2-4`). |

Optional, only if diagnostics/persistence are requested later:

- `timetravel/migrations.py` — schema versioning applied through `db.connect()`.
- `timetravel/artifacts.py` — per-session file registry, checksums, cleanup.
- `timetravel/engine_models.py` — stdlib `dataclass` types for events/plans/checks.

Avoid adding a new static JS/CSS asset: `server.py` only serves `/` and `/index.html` (`server.py:93-94`).

---

## 9. Contracts that must not change

### 9.1 Database / SQL

- Table and column names in `timetravel/db.py:27-48`.
- `changelog` columns `id, ts, tbl, op, pk, old, new`; `query_log` columns `id, ts, source, sql, rows_affected`.
- Trigger names `{table}_ai/_au/_ad` and op codes `I/U/D`.
- `app_now` SQL function name (`timetravel/db.py:54`), used by `app/handlers.py:7,32`.
- `sqlite3.Row` row factory (`timetravel/db.py:53`).
- `sqlite_sequence` seed `('orders', 1000)` (`timetravel/db.py:61`) and order ID range `1001–1043`.
- `INV_UPSERT`, `CUST_SQL`, `ORDER_SQL`, `ITEM_SQL`, `BACKORDER_SQL`, `STATEMENTS` and their execution order (`timetravel/tools.py:16-24,84-94`).
- Autocommit connections and explicit transaction ownership (`timetravel/db.py:52`, `app/handlers.py:29-48`, `timetravel/tools.py:269-278`).

### 9.2 Function signatures / return shapes

- `db.connect(path=LIVE)`, `db.create_schema(c)`, `db.clone(src_conn, dest_path)`, `db.changes_after(conn, ts)`, `db.reverse_changes(conn, since_ts, events)`.
- `tools.rewind_branch_tool(live, target_ts, branch_path)` → `(open connection, {events_reversed, inventory_rows, units, zero_rows, ms})`.
- `tools.extract_delta_tool(live, target_ts, incident_ts)` → `{orders, items, customers, post_crash, pre_crash}`; orders include `phase` and `items`.
- `tools.plan_merge_tool(live, branch, delta, scratch_path)` → `(plan, expected, summary)`, with plan keys `inventory_rows, customer_rows, order_rows, item_rows, backorder_ids`.
- `summary` keys: `restored_rows, orders_preserved, order_ids, units_before, units_after, zero_before, zero_after, conflicts, resolver_checks, dry_run, dry_run_ok, guardrails, risk, preview_sql, live_marker` (`timetravel/tools.py:182-194`).
- `conflicts[].kind` ∈ `id-collision | duplicate-idempotency-key | orphan-sku | oversell`; `risk = {score, label, factors}` with `(text, int)` factor tuples.
- `run_checks()` → ordered list of `{name, ok, detail}` (`timetravel/tools.py:67-81`).
- `guard.analyze(sql, approved=False)` → `{allowed, rule, sql, why}` (`timetravel/guard.py:8-23`).
- `apply_recovery_tool(...)` eight-argument signature; `undo_recovery(live, backup_db, backup_src)`.
- `agent.start(prompt, background=True)`, `approve(sid)`, `undo(sid)` return `Session`.
- `Session.to_json()` keys: `id, prompt, phase, events, parsed, branch, timeline, delta, plan, patch, result, can_approve, can_undo` (`timetravel/agent.py:49-61`).
- Phase strings: `starting, parsing, branching, extracting_delta, planning, diagnosing, awaiting_approval, applying, applied, undone, error`.
- `events` must stay append-only; UI tracks them by index (`web/index.html:104`).
- `patch` must continue to omit `patched_source` in JSON (`timetravel/agent.py:50-52`).
- `server.post()` routes, payload keys, status codes, and `{"error": ...}` conventions.
- `/api/state` fields consumed by UI: `now`, `inventory.{skus,units,zero,sample}`, `orders`, `incident`, `order_dots`, `patched`, `warm.{ms,events}` (`server.py:44-46`, `web/index.html:94-100`).
- Session fields consumed by UI: `events`, `phase`, `can_approve`, `can_undo`, `timeline.target`, `plan`, `patch`, `result`, exact phase `"undone"` (`web/index.html:102-125`).
- Environment variables: `PORT` (`server.py:119`), `TT_PACE` (`timetravel/agent.py:10`).

---

## 10. Potential integration conflicts with other teammates

| Teammate area | Conflict surface | Mitigation |
|---|---|---|
| AI agent / LLM | `agent.py` intent parser, phases, events, session JSON; README invites replacing regex with Bedrock/Strands. | Engine must not own orchestration or phase names. Expose pure functions; let `agent.py` keep HITL and feed behavior. |
| Tool layer / patch generation | `tools.py` wrappers and `_patch_source()` exact-text matching. | Additive engine; optional delegation behind identical tool signatures. Never reformat `app/handlers.py:16-17` or the SQL string. |
| API layer | Monolithic `server.py`; all routes use exact string paths and split session IDs by `/`. | No new route needed. If diagnostics are added, use new nested keys only. Preserve status codes and error JSON. |
| Frontend | `web/index.html` is the only served asset and reads exact field names; UI uses a 360s timeline while server emits 600s of dots. | Do not change field names, event levels, phase strings, `SHOW` SKUs, or status string `"backorder"`. |
| Shared mutable files | `app/handlers.py` is overwritten by patch/undo/reset; `data/*.db` is wiped by reset; `backup_*.py` is not. | Task 3 should not edit these. Prefer `.db`-suffixed artifacts and per-session names because `db.clone()` deletes an existing destination (`timetravel/db.py:76-77`). |
| Performance / warm badge | `warm_loop` clones live every 4 seconds under `db.LOCK` (`server.py:15-27`). | Any engine change that slows `clone()` or holds `LOCK` longer will visibly change the UI badge. |
| Seed / test fixtures | Exactly one conflict and specific row counts are asserted by `tests/e2e.py`. | Do not change seed constants, SQL strings, or order ID sequencing. |
| Concurrency | `db.LOCK` is process-local; a teammate adding another process/server breaks the stale-marker assumption. | Engine should recheck the marker inside `BEGIN IMMEDIATE` and document single-process scope. |

---

## 11. Recommended implementation architecture

### 11.1 Layering

```text
server.py                       HTTP + state (unchanged unless additive diagnostics)
  └── timetravel/agent.py       HITL orchestration, sessions, event feed (unchanged)
        └── timetravel/tools.py stable tool façades (internals may delegate)
              └── timetravel/engine.py   NEW: recovery core
                    ├── timetravel/db.py       connect / clone / LOCK / clock / TABLES
                    └── timetravel/guard.py    SQL policy
```

### 11.2 Proposed `timetravel/engine.py` responsibilities

Keep it pure, deterministic, and stdlib-only:

1. **Event model and selection**
   - Normalize `changelog` rows into a small stdlib record (`dataclass` or `dict`).
   - Select by **changelog id** (monotonic) as the primary sequence; retain `ts` only for human timelines.
   - Provide an id-based alternative to `db.changes_after()` without changing its signature.

2. **Correct compensation**
   - Restore the **old PK** on UPDATE and in all `WHERE` clauses.
   - Reverse strictly newest-first by `changelog.id`.
   - Temporarily suppress CDC triggers on the branch/scratch connection during compensation, or filter synthetic events, so the branch is a true point-in-time image.
   - Keep `db.reverse_changes()` as a compatibility façade.

3. **Snapshot / branch lifecycle**
   - Wrap `db.clone()` with per-session artifact naming, cleanup registration, and guaranteed connection closure.
   - Never pass `LIVE` as a clone destination.
   - Do not enable WAL journaling in Phase 2.

4. **Delta and three-way merge**
   - Compute row-level diffs for `customers`, `inventory`, `orders`, and `order_items` from `(base, live, delta)`.
   - Resolve or explicitly reject id collisions, duplicate idempotency keys, orphan SKUs, and oversells.
   - Preserve current conflict kinds and messages for the UI/e2e contract.

5. **Verification and cutover**
   - Validate FK, CHECK, row identity, content checksums, preserved order state, and expected inventory before commit.
   - Recheck `MAX(changelog.id)` inside `BEGIN IMMEDIATE`, under `db.LOCK`.
   - Take the backup snapshot inside the same critical section.
   - Keep DB commit and source patch as separate steps; document/flag the residual cross-resource limitation rather than silently claiming atomicity.

6. **Undo**
   - Restore from a validated backup with checksum metadata; restore source; mark artifacts as consumed.
   - Do not change `agent.undo()` phase transitions.

### 11.3 Design rules

- Additive only; no new dependency.
- All connections via `db.connect()`; all shared-state access via `db.LOCK`.
- Deterministic outputs; no network calls; no LLM calls; no hidden global clock mutation.
- Existing tool return dictionaries remain the public seam.
- Prefer new nested diagnostic keys over changing existing fields.
- Tests must be standalone stdlib scripts and must leave `app/handlers.py` pristine or restore it.

---

## 12. Implementation plan for Task 3 — awaiting approval

### Phase 1 — Analysis (complete)

- Full repository inspection completed.
- Database technology and schema confirmed.
- Current recovery flow, crash simulation, APIs, agent integration, tests, and config identified.
- Baseline e2e verified in an isolated copy: `E2E PASS`.
- No repository file modified; this document created.

### Phase 2 — Implementation (do not start without approval)

1. Create `timetravel/engine.py` with the additive core described in §11.2.
2. Create `tests/test_engine.py` covering:
   - multiple updates to the same row,
   - insert-then-delete within the window,
   - primary-key changes,
   - clock-offset skew,
   - trigger-generated synthetic branch events,
   - orphan SKU and idempotency collisions,
   - stale marker rejection,
   - artifact cleanup / backup validation.
3. Run `python3 tests/test_engine.py`.
4. Run `python3 tests/e2e.py` in an isolated copy first. This test intentionally patches `app/handlers.py`, creates/removes DB files, and ends with `seed.reset()`.
5. Only if approved, make minimal internal delegation changes in `timetravel/tools.py` so the existing pipeline uses the engine while keeping every signature and return shape unchanged.
6. Optionally add new nested diagnostics to `api_state()` or `Session.to_json()`; never rename or remove existing keys.
7. Re-run `python3 tests/e2e.py` and a manual HTTP smoke of `/api/state`, `/api/rewind`, `/api/session/{id}`, `/approve`, and `/undo`.
8. Verify `git status` shows only intended new/modified files; install no dependencies.

### Phase 3 — Optional hardening (separate approval)

- Schema migrations/versioning.
- Durable session and plan persistence.
- Real SQLite WAL mode with coordinated reset cleanup.
- Cross-process locking.
- Replacing regex intent parsing/guard SQL analysis with an LLM or tokenizer — owned with the AI teammate.

**Phase 2 approval was subsequently given; Phases 2–6 are implemented.**

---

## 13. Phase 4 — Foreign-key-aware recovery support

### 13.1 What is implemented

Phase 4 adds `timetravel/recovery/dependencies.py` and extends the planner, validator, and executor. It does not change any unrelated application module, API route, UI file, seed fixture, or existing tool signature.

For every plan, the engine now:

1. Reads `PRAGMA foreign_key_list` for all captured tables.
2. Identifies parent tables, child tables, and each single-column FK relationship.
3. Adds dependency edges between affected history events.
4. Produces a deterministic `execution_order` while preserving the captured newest-first order when no dependency applies.
5. Detects FK conflicts before any write.
6. Executes the ordered plan in one `BEGIN IMMEDIATE` transaction.
7. Verifies `PRAGMA foreign_key_check` plus every declared relationship after execution.
8. Rolls back the entire recovery if any step or verification fails.

The observed relationships in the current schema are:

| Parent | Child | Delete action |
|---|---|---|
| `customers.id` | `orders.customer_id` | `NO ACTION` |
| `inventory.sku` | `order_items.sku` | `NO ACTION` |
| `orders.id` | `order_items.order_id` | `NO ACTION` |

### 13.2 Ordering rules

| Compensation | Order |
|---|---|
| Restore deleted parent (`source D` → `I`) | Parent before child |
| Restore deleted child (`source D` → `I`) | After its restored parent |
| Reverse inserted parent (`source I` → `D`) | After its inserted children |
| Reverse inserted child (`source I` → `D`) | Before its inserted parent |
| Non-PK related `UPDATE` | Captured order unless a restored parent must precede a child update |
| Repoint child FK before parent delete | Child update before parent delete |

Cascading `ON DELETE CASCADE` is handled conservatively: if a parent deletion would cascade-delete child rows that are not explicitly removed by the same plan, the recovery is rejected with `cascade-child-loss`. The same guard reports `dependent-child-loss` for `SET NULL` / `SET DEFAULT` and `dependent-rows-exist` for `NO ACTION` / `RESTRICT`.

### 13.3 Conflict kinds added

- `missing-parent-reference`: a row to restore or update references a parent that does not exist and is not restored by the same plan.
- `dependent-rows-exist`: deleting a parent would leave or break child rows.
- `cascade-child-loss`: deleting a parent would cascade-delete children outside the plan.
- `dependent-child-loss`: deleting a parent would silently alter children through `SET NULL` / `SET DEFAULT`.
- `simulation-failure` and `foreign-key-violation` remain from the earlier validation layers.

All conflicts are surfaced through `RecoveryConflictError.conflicts` before the live transaction starts.

### 13.4 Unsupported relationship scenarios

The engine deliberately rejects or does not claim support for the following:

- Composite or multi-column foreign keys.
- Foreign keys to tables outside the captured `db.TABLES` registry or to attached databases.
- Foreign keys that target a non-primary-key `UNIQUE` column; the row graph addresses rows only by the registered single-column key.
- Self-referential foreign keys such as `employees.manager_id`.
- `UPDATE` statements that change a primary key, including `ON UPDATE CASCADE` remaps; the prior engine cannot safely reconstruct identity and all child references from the captured row image alone.
- Dependency cycles between tables that cannot be topologically ordered.
- Cascade side effects whose child changes were not captured by the installed triggers; recovery relies on SQLite emitting child `D`/`U` events for cascaded rows.
- Legitimate child rows introduced after the faulty transaction when reversing an inserted parent: these are detected as `cascade-child-loss` or `dependent-rows-exist` and must be handled intentionally rather than silently deleted or altered.
- Schema changes, DDL, trigger bypass, or writes from another process that are not present in the durable transaction history.

Unsupported cases raise `UnsupportedRelationshipError` during planning or produce a typed conflict before execution. The engine never synthesizes or executes arbitrary SQL for them.

### 13.5 Tests

`tests/test_foreign_key_recovery.py` covers:

- parent deletion with dependent child and grandchild rows;
- child-only deletion;
- multiple related `UPDATE` operations;
- cascading parent deletion and restoration in parent → child → grandchild order;
- reverse inserted records in child → parent order;
- duplicate parent primary key rejection;
- missing parent reference rejection;
- dependent child rows blocking parent deletion;
- cascade child loss detection;
- partial failure rollback with all related changes reverted;
- explicit rejection of non-PK and composite FK shapes.

Every successful recovery asserts `PRAGMA foreign_key_check` and per-relationship orphan checks. No existing application module was modified for Phase 4.

Historical Phase 4 verification: `python3 -m unittest discover -s tests -p 'test_*.py' -v` passed 86 tests at that snapshot; `python3 -m compileall -q timetravel tests` passed; the existing `python3 tests/e2e.py` regression passed in an isolated copy. Current suite counts are recorded in [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md).

---

## 14. Phase 6 — Checksum-based recovery verification

### 14.1 What is implemented

Phase 6 adds `timetravel/recovery/verification.py` and integrates it into `execute_plan()`. It uses only the Python standard library and SQLite. No unrelated application module, API route, UI file, seed fixture, or existing tool signature was changed.

Verification streams every captured business-table row into a temporary SQLite checksum database in batches of 1,000 rows. Row checksums include the table name, primary key, and all columns. A second content checksum excludes the primary key so the comparison can detect a row whose primary key changed while its other values stayed the same. Values are normalized deterministically before hashing, including `NULL`, booleans, finite floats, `NaN`/`±inf`, and BLOBs.

`capture_reference()` uses `db.clone()` to build a consistent reference snapshot without writing into the caller's snapshot directory. `compare_baselines()` attaches the original and recovered checksum databases and reports:

- `original_checksum`
- `recovered_checksum`
- `total_rows_checked`
- `matching_rows`
- `mismatching_rows`
- `missing_rows`
- `unexpected_rows`
- `primary_key_mismatches`
- `integrity_status` (`VERIFIED` or `FAILED`)

It also returns `checksum_match`, `modified_rows`, `checked_tables`, and bounded samples for mismatches.

### 14.2 Atomic cutover behavior

`_simulate_plan()` now builds the expected post-recovery checksum baseline from the simulation clone. `execute_plan()` uses that baseline by default, so legitimate later transactions are preserved rather than treated as corruption. A caller may supply an explicit `reference` baseline when the expected final state needs to be defined externally.

Inside the same `BEGIN IMMEDIATE` transaction that applies the recovery steps, the engine runs `verify_state_against()` before `COMMIT`. The result is appended to `checks` as `Checksum verification` and returned as `result["verification"]`. If the status is not `VERIFIED`, the engine raises before commit, rolls back all recovery writes, marks the audit run `rolled-back`, records failed actions, and never writes `committed`.

### 14.3 Tests

`tests/test_integrity_verification.py` covers:

- agreement between `integrity.checksum()` and `verification.checksum_database()`;
- successful verification of identical state;
- detection of a modified row;
- detection of missing rows, unexpected rows, and primary-key mismatches;
- engine rollback and `rolled-back` audit status when checksum verification fails.

The Phase 5 second-crash test also asserts that the generated report contains `integrity_status: VERIFIED` and zero unexpected rows.

---

## 15. Phase 7 — Recovery performance benchmarking

### 15.1 Implementation

Phase 7 adds `benchmarks/generate_data.py`, `benchmarks/benchmark_recovery.py`, and the measured artifacts `BENCHMARK_REPORT.md` and `benchmarks/benchmark_results.json`. The suite uses only the standard library and SQLite, generates deterministic datasets, injects one faulty `UPDATE inventory SET stock = 0` transaction, builds a scoped recovery plan, executes recovery with checksum verification, and records wall-clock and phase timings.

Before the final run, recovery paths were optimized without changing existing API contracts:

- `RecoveryStep.old_row()`, `RecoveryStep.new_row()`, and `RecoveryPlan.fingerprint()` cache parsed payloads and plan fingerprints.
- Dependency analysis and integrity checks reuse cached rows/columns instead of reparsing every step.
- Recovery action auditing is batched through `executemany()`.
- `verification.build_baseline()` uses batched checksum inserts and temporary-database pragmas.
- `verification.compare_baselines()` combines count checks into one query and uses a single streaming merge to collect mismatch samples rather than expensive cross-database SQL scans.
- `execute_plan(..., timing=None)` adds an optional timing hook; default behavior is unchanged.

### 15.2 Measured outcome

The full matrix ran with 1,000 / 10,000 / 100,000 / 500,000 inventory rows, three iterations each. All 12 runs were committed, all reported `integrity_status: VERIFIED`, and there were zero errors. Median total recovery durations were 2.185059 s, 28.365067 s, 347.718108 s, and 652.286040 s respectively.

The dominant costs at 500,000 rows were live apply (204.667 s), preflight validation (173.872 s), simulation replay (130.562 s), and checksum verification (63.026 s). Peak process high-water RSS reached approximately 1.77 GB on the 8 GB benchmark machine. Full averages, medians, environment details, methodology, and recommendations are in `BENCHMARK_REPORT.md`.

### 15.3 Verification

Historical Phase 7 verification: `python3 -m unittest discover -s tests -p 'test_*.py' -v` passed 86 tests at that snapshot and `python3 -m compileall -q timetravel tests benchmarks` passed. The benchmark runner was executed directly to produce the raw JSON results. Current suite counts are recorded in [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md).

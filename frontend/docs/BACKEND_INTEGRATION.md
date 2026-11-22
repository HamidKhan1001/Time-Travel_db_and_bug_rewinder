# Backend integration guide

The frontend runs on mock data by default and on the real Python backend (`server.py`) with `npm run dev:live`. This guide lists every backend call, the endpoint it uses, and the data shape each screen expects.

## How the layers fit

```
pages/ + components/   (UI only: never fetch, never import mocks)
        |
context/DemoContext.jsx (app state + actions, calls the service layer)
        |
services/api.js        (ONE function per backend action; picks mock or real)
        |-- mocks/mockServer.js        (mock mode, the default)
        '-- services/backend.js        (real mode) --> services/httpClient.js --> server.py
                  '-- services/adapters.js   (pure functions: backend JSON -> UI shapes, unit-tested)
```

## Running against the real backend

```bash
python3 server.py            # repository root, port 8000
cd frontend && npm run dev:live
```

Vite proxies `/api` to `http://127.0.0.1:8000` (set `API_PROXY_TARGET` to change it), and the server also allows CORS from `localhost`/`127.0.0.1`. `npm run build:live` produces the bundle that `server.py` serves at `/app/`.

## Endpoint mapping

| Service function | Backend call | Notes |
|---|---|---|
| `getScenarios()` | none (static list in `adapters.js`) | Only `warehouse-wipe` is available. The second scenario exists in the backend tests but has no API yet. |
| `getLiveSnapshot()` | `GET /api/state` | Inventory is the 5 sample SKUs the backend returns. `previousStock` is remembered client-side between snapshots. |
| `triggerWarehouseSync()` | `POST /api/demo/crash` then `GET /api/state` | |
| `placeOrders()` | `POST /api/demo/orders` then `GET /api/state` | Blocked client-side if orders #1041+ already exist (the backend would add duplicates). |
| `resetDemo()` | `POST /api/demo/reset` then `GET /api/state` | Also clears the audit log (the backend stores it in the database that is reset). |
| `runTimeTravel()` | `POST /api/rewind`, then polls `GET /api/session/<id>` every 350 ms | `phase` maps to the 7 progress steps; resolves when `phase` is `awaiting_approval`. Cancel stops polling; the session itself keeps running on the server. |
| `approveRecovery()` | `POST /api/session/<id>/approve` | Smoke checks come from `result.checks`. |
| `discardRecovery()` | `POST /api/session/<id>/discard` | New endpoint. Only valid while `awaiting_approval`. |
| `undoRecovery()` | `POST /api/session/<id>/undo` | |
| `getAuditLog()` | `GET /api/audit?search=&status=&scenario=&page=&pageSize=` | New endpoint, built from the durable audit events. In-flight sessions are not listed. |
| `getAuditSummary()` | `GET /api/audit/summary` | New endpoint. Discarded plans count in the total but not in the success rate. |
| `getAuditEntry()` | `GET /api/audit/<id>` | New endpoint. |

Field mapping worth knowing: backend risk is 0-100 and the UI uses 0-1; `legitimateRowsLost` is `0` only when the dry run on the clone passed (otherwise `null`, shown as a dash); when the agent finds no code fix, `plan.patch` is `null` and approval depends on the clone dry run.

## Actions that need the backend

| Service function | Used on | Triggered by | PRD reference |
|---|---|---|---|
| `getScenarios()` | Console, Audit log filters | App start | §6 "second incident scenario" |
| `getLiveSnapshot(scenarioId)` | Console, Review | App start, Retry | §5 steps 1–2 |
| `triggerWarehouseSync(scenarioId)` | Console | **Sync Warehouse** / **Re-run Sync** | §5 steps 1 and 6 |
| `placeOrders(scenarioId)` | Console | **Place 3 Orders** | §5 step 2 |
| `resetDemo(scenarioId)` | Header, scenario switch | **Reset demo** → confirm | §12 "Reset button" (`reset.py`) |
| `runTimeTravel({ scenarioId, prompt }, { onProgress, signal })` | Console | **Run time-travel** | §5 step 3, §6 streaming progress |
| `approveRecovery(planId)` | Review | **Approve & go live** → **Apply to live** | §5 step 5, §7 approval gate |
| `discardRecovery(planId)` | Review | **Discard plan** → confirm | (assumed — not in PRD) |
| `undoRecovery(recoveryId)` | Review | **Undo recovery** → confirm | §5 step 7 |
| `getAuditLog({ search, status, scenario, page, pageSize })` | Audit log | Page load, filters, pagination | §6 audit log |
| `getAuditSummary()` | Audit log, header badge | Page load, after any recovery | §6 audit log |
| `getAuditEntry(id)` | Audit log drawer | Clicking a row | §6 audit log |

### Streaming progress (`runTimeTravel`)

The real backend reports progress through the session `phase`, which `adapters.stepsFromSession` turns into these events (the planning phase covers steps 2-4 together because the backend does not report them separately). The UI expects progress events while the agent runs on the clone:

```js
onProgress({ stepIndex: 0, status: 'running', log: 'Forking clone from snapshot #88f2' })
onProgress({ stepIndex: 0, status: 'done',    log: 'Clone branch cl-9942-alpha ready' })
// …steps 0–6, then the promise resolves with the RecoveryPlan
```

Step indexes match `src/constants/recoverySteps.js`. If the backend uses Server-Sent Events or WebSockets, read the stream inside `runTimeTravel` and call `onProgress` for each event. `signal` is an `AbortSignal` (the **Cancel run** button).

## Data shapes

These are the shapes the components read. Field names are suggestions — change them in one place (`api.js`) if the backend differs.

### Scenario
```js
{ id: 'warehouse-wipe', code: 'S02', name: 'Warehouse Wipe (Stock 0)', description: '…', available: true }
```

### LiveSnapshot
```js
{
  scenarioId: 'warehouse-wipe',
  dbVersion: 'v1.4.2',
  inventory: [{ sku, name, category, stock, previousStock, limited, status: 'ok'|'zeroed'|'restored'|'updated' }],
  orders: [{ id: '#1041', sku, item, qty, user, placedAt: '02:14:09',
             status: 'fulfilled'|'oversold'|'partial', fulfilledQty?, backorderedQty?, afterCrash: true }],
  changeLog: [{ id, time: '02:14:07', label: 'CRASH: Warehouse Sync Executed', kind: 'ok'|'fail'|'crash'|'recovery'|'undo' }],  // newest first
  lastAction: { label: 'Warehouse sync · touched 5 rows', tone: 'danger'|'success'|'info', time } | null,
  incident: { active: true, crashAt: '02:14:07', rowsTouched: 5 } | null,
  patched: false,            // true after a recovery with a patch is live
  recovery: { id, status: 'live', appliedAt } | null,
}
```

### RecoveryPlan
```js
{
  id: 'R-0008', prompt, createdAt,
  cloneBranch: 'cl-9942-alpha', cloneRef: 'main-clone@88f2', targetCommit: '#88f2',
  rewindTarget: '02:14:06.900', crashAt: '02:14:07.120', guardrailAdjusted: false, parsedBy: 'ai'|'rule-based',
  stats: { changes, kept, discarded, conflicts, conflictsResolved, legitimateRowsLost },
  risk: { score: 0.22 },        // 0–1; UI bands: <0.34 Low, <0.67 Medium, else High (assumption)
  confidence: 0.91,             // 0–1 (PRD stretch goal)
  verifiedSuites: 8,
  operations: [{ id, operation: 'REPLAY_ORDER', target: 'order #1041', targetNote?, decision: 'kept'|'resolved'|'discarded',
                 reason: 'plain string' | [{ text, tone?: 'strong'|'success'|'warning'|'danger' }],
                 details: [{ label, value }] }],
  conflict: { item, sku, order, requestedQty, availableQty, strategy: string | segments[] } | null,
  patch: { file, hunk, lines: [{ type: 'context'|'add'|'del', text }],
           verification: { passed: true, rowsTouchedBefore: 5, rowsTouchedAfter: 1 } },
}
```

### approveRecovery → result
```js
{ snapshot: LiveSnapshot, recovery: { id, appliedAt, smokeChecks: [{ label, passed }] }, auditEntry: AuditEntry }
```

### AuditEntry
```js
{ id: 'R-0007', status: 'applied'|'undone'|'discarded'|'failed', startedAt: ISO string, scenario: 'Warehouse Wipe (Stock 0)',
  prompt, rewindRef: '#c89f21a', delta: { kept, discarded, conflicts } | null, rowsLost: 0 | null,
  risk: 0.12 | null, durationSec: 41.2 | null }
```

### getAuditLog → result
```js
{ items: AuditEntry[], total: 1482, page: 1, pageSize: 5 }
```

### getAuditSummary → result
```js
{ totalRecoveries: 1482, today: 12, successRate: 99.4, targetSuccessRate: 99 }
```

## Open questions

Resolved by the real backend: **2** (a discard endpoint was added), **6** (the audit log is cleared by Reset demo; it lives in the demo database), **8** (the drawer still shows the summary only).

These affect the UI and are not settled by the PRD:

1. **Conflict resolution** — does the agent always resolve conflicts itself (the UI shows them read-only), or should the human choose?
2. **Discard** — the PRD has no reject path; the UI adds **Discard plan**. Confirm, or remove it.
3. **Risk score scale** and bands; **confidence** threshold for escalating to a human.
4. **Failures** — what happens when the SQL guard blocks a statement, the patch fails on the clone, or a smoke check fails after the apply? (The UI disables Approve when `patch.verification.passed` is false.)
5. **Undo window** — the UI only allows undoing the latest applied recovery.
6. **Reset demo** — the UI assumes the audit log is kept.
7. **Second scenario** — content not defined yet; the mock lists it as unavailable.
8. **Audit detail** — the drawer shows the summary only. A full record (step timeline, merge decisions, patch) needs more fields in `getAuditEntry`.

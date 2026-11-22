# API Reference

The demo server is a Python `ThreadingHTTPServer` listening on `127.0.0.1:8000` by default. Set `PORT` to change the port.

## General behavior

- Success for POST routes is currently HTTP `200` with a route-specific JSON body.
- Unknown routes return `404 {"error":"unknown route <path>"}`.
- Request/handler errors return `400 {"error":"<message>"}`.
- Unknown session GET requests return `404 {"error":"session not found"}`.
- No authentication or external authorization mechanism is implemented.
- Approval is enforced only by the in-memory session phase; `/api/session/<id>/approve` must target a session in `awaiting_approval`.

## GET `/`

Serves `web/index.html` as HTML.

## GET `/index.html`

Alias for `/`.

## GET `/js/recovery_data.js`, GET `/js/recovery_view.js`

Serves the Phase 4 frontend modules with `application/javascript; charset=utf-8`. Only these two filenames are allowed; any other path under `/js/` returns `404`.

## GET `/api/state`

Returns live inventory, orders, incident, timeline dots, warm-branch metrics, and patch state.

```json
{
  "now": 1795340000.0,
  "inventory": {
    "skus": 1420,
    "units": 163393,
    "zero": 0,
    "sample": [{"sku":"APX-0007","name":"Alpine Water Bottle","stock":120}]
  },
  "orders": [],
  "incident": null,
  "order_dots": [],
  "patched": false,
  "warm": {"ms": 12.4, "at": 1795340000.0, "events": 1434}
}
```

## GET `/api/session/<id>`

Returns the full in-memory session JSON. Unknown IDs return `404`.

The `phase` field includes `starting`, `parsing`, `branching`, `extracting_delta`, `planning`, `diagnosing`, `awaiting_approval`, `applying`, `applied`, `undone`, or `error`.

### Phase 4 visualization fields

These keys are additive and do not replace existing session fields.

| Field | Meaning |
|---|---|
| `recovery_preview` | Read-only proposed projection derived from the merge plan and live state at plan time. `null` before planning completes. |
| `actual_recovery` | Real post-commit values for the sampled projection rows. `null` until approval succeeds. |
| `verification` | Backend verification result from post-apply checks only. `null` before execution. |
| `undo_state` | Backend-derived undo availability, initiation, success, or failure. |

`recovery_preview` shape:

```json
{
  "label": "PROPOSED RECOVERY PROJECTION — NOT APPLIED",
  "generated_at": 1795340000.0,
  "source": "Legacy merge plan plus read-only live database state",
  "row_count": 1420,
  "rows": [{
    "id": "inventory:APX-0007:stock",
    "table": "inventory",
    "key": "APX-0007",
    "field": "stock",
    "operation": "UPDATE",
    "before": 0,
    "after": 120,
    "note": "Idempotent inventory upsert restores the pre-incident stock value."
  }],
  "sample_truncated": true,
  "tables": ["inventory"],
  "operation_counts": {"INSERT": 0, "UPDATE": 1420, "DELETE": 0},
  "counts_by_table": {"inventory": {"INSERT": 0, "UPDATE": 1420, "DELETE": 0}},
  "delete_semantics": "The approved merge plan contains no DELETE statements; no deletions are proposed.",
  "conflicts": [],
  "validation": {"dry_run_ok": true, "checks": [], "risk": {"score": 8, "label": "LOW", "factors": []}}
}
```

`rows` is a bounded sample; `operation_counts` and `row_count` cover the full plan. `DELETE` is reported as `0` because the HTTP recovery path uses idempotent upserts and status updates, not delete statements. A future backend that exposes compensating DELETE steps should supply its own row entries; the renderer already supports `[DELETE]` rows.

`actual_recovery` shape:

```json
{
  "captured_at": 1795340100.0,
  "source": "Live database read after the approved recovery committed",
  "values": {"inventory:APX-0007:stock": 120}
}
```

A sampled value that cannot be read after apply is represented as `{"unavailable": "<reason>"}` rather than invented.

`verification` shape:

```json
{
  "status": "passed",
  "method": "Post-apply smoke checks recorded by the recovery engine",
  "checks": [{"name": "Foreign keys intact", "ok": true, "detail": "0 violations"}],
  "completed_at": 1795340100.0,
  "checksum": {"status": "unavailable", "reason": "The HTTP recovery path exposes post-apply smoke checks; checksum verification is not available on this session."}
}
```

`status` is `passed` or `failed` only when the backend executed checks. It is `unavailable` when checks are absent. The UI separately shows checksum verification as unavailable; checksum verification exists in `timetravel/recovery` but is not wired into the HTTP session path.

## GET `/api/session/<id>/audit`

Returns durable session audit events stored in SQLite.

```json
{
  "session_id": "INC-12ABC3",
  "events": [{
    "id": 1,
    "session_id": "INC-12ABC3",
    "event_type": "recovery_initiated",
    "status": "started",
    "ts": 1795340000.0,
    "detail": {"prompt_length": 96}
  }]
}
```

This route does not require the session object to remain in memory. Audit events are durable in SQLite, so it can return history after a process restart. IDs with no audit history return `404 {"error":"audit history not found"}`. Resetting the demo database removes session audit records.

## POST `/api/orders`

Places an idempotent order and updates inventory.

Request:

```json
{
  "customer_id": 1,
  "idem_key": "optional-key",
  "items": [{"sku":"APX-0001","qty":2}]
}
```

Success:

```json
{"order_id":1041,"total_cents":4800}
```

Duplicate idempotency key:

```json
{"order_id":1041,"duplicate":true}
```

Missing customers, missing SKUs, invalid quantities, and database errors return HTTP `400` with `{"error":"<message>"}`.

## POST `/api/admin/sync-stock`

Sets inventory stock through the demo storefront handler.

Request:

```json
{"sku":"APX-0007","stock":0}
```

Success:

```json
{"updated_rows":1420}
```

The result depends on the currently loaded handler: the buggy handler updates 1,420 rows, while the patched handler updates exactly the requested SKU and returns `1`.

The patched handler requires `sku`; missing SKU raises a `ValueError` and is returned as HTTP `400`.

## POST `/api/demo/reset`

Clears in-memory sessions and resets the demo database, handler source, and seeded data. This endpoint is destructive to the demo database and should not be called by normal recovery clients during rehearsal without intention.

Success:

```json
{"ok":true}
```

## POST `/api/demo/crash`

Triggers the intentional warehouse-sync crash using `APX-0007` and stock `0`.

Success:

```json
{"updated_rows":1420}
```

The result depends on the currently loaded handler: the buggy handler updates 1,420 rows, while the patched handler updates exactly the requested SKU and returns `1`.

After the demo bug is patched, this action should normally update one row.

## POST `/api/demo/orders`

Places the three built-in demonstration orders `1041`–`1043`.

Success:

```json
{"orders":[{"order_id":1041,"total_cents":...},{"order_id":1042,"total_cents":...},{"order_id":1043,"total_cents":...}]}
```

## POST `/api/rewind`

Starts a recovery session asynchronously. The server calls `agent.start(prompt)` with background execution enabled.

Request:

```json
{"prompt":"Take the business back to 2 minutes ago, keep the 3 orders, and fix the bug"}
```

Success:

```json
{"id":"INC-12ABC3"}
```

Failure is returned through the session state with `phase:"error"`; HTTP success returns the session ID when the session was accepted.

## POST `/api/session/<id>/approve`

Approves and applies an awaiting session.

No request body is required. The server currently tolerates `{}`.

Success: returns the full updated session JSON with `phase:"applied"`.

Invalid phase: HTTP `400` with `{"error":"Session is '...', not awaiting approval."}`.

Unknown session: HTTP `404` through `KeyError` route handling.

## POST `/api/session/<id>/undo`

Restores the pre-recovery database snapshot and source-code backup.

Success: returns the full session JSON with `phase:"undone"`.

Invalid phase: HTTP `400` with `{"error":"Nothing to undo."}`.

Unknown session: HTTP `404`.

## GET `/api/session/<id>/events`

Streams durable and live recovery/audit events for one session using Server-Sent Events.

Headers:

- `Accept: text/event-stream`
- Optional `Last-Event-ID: <non-negative audit ID>`

The query parameter `last_event_id=<id>` is also accepted.

Response headers:

- `Content-Type: text/event-stream; charset=utf-8`
- `Cache-Control: no-cache`
- `Connection: keep-alive`
- `X-Accel-Buffering: no`

The stream sends `retry: 3000`, replays session-scoped audit events after the supplied ID, then polls SQLite for new audit events. It sends a heartbeat comment every 15 seconds and closes after 300 seconds; `EventSource` reconnects automatically.

Named event types:

- `session_started`
- `preview_generated`
- `approval_granted`
- `approval_rejected`
- `recovery_started`
- `integrity_verified`
- `recovery_completed`
- `recovery_failed`
- `undo_started`
- `undo_completed`
- `undo_failed`
- `stream_error`

Envelope:

```text
id: 17
event: recovery_completed
data: {"id":17,"session_id":"INC-12ABC3","event_type":"recovery_completed","timestamp":1795340000.0,"status":"completed","payload":{"code_patched":true}}
```

Stable audit IDs support deduplication and reconnection replay. Delivery is at-least-once for persisted audit history, not exactly-once. A stream does not hold a SQLite transaction open.

Unknown or historical-empty session IDs return `404`. An active in-memory session with no history may stream until events arrive. Invalid IDs or malformed `Last-Event-ID` values return `400`.

There is no SSE authentication or RBAC. The local demo exposes only the requested session's persistent audit events.

## Current limitations

- Session state is in-memory; process restart removes sessions.
- Session audit events are durable in SQLite, but their session summary is not restored into memory.
- No authentication or RBAC is implemented.
- SSE is implemented with bounded SQLite polling and is not an external pub/sub system.
- Database rollback and application source rollback are not a distributed atomic operation.
- SSE delivery is at-least-once and limited to SQLite audit history; live events are not durable in an external broker.

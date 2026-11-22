# 0005. The UI polls the session and reads the API through adapters

**Status:** accepted.

## Context
The React screens were designed against mock data with their own field names (`RecoveryPlan`, `LiveSnapshot`, `AuditEntry`). The Python API has its own shapes (session JSON with `plan`, `patch`, `delta`). The backend also offers an SSE stream of audit events.

## Decision
Components never call `fetch`. They use `services/api.js`, which routes to the mock server (`npm run dev`) or to `services/backend.js` (`npm run dev:live`). `services/adapters.js` converts backend JSON to the shapes the screens read and is pure and unit-tested. Progress is shown by polling `GET /api/session/<id>` every 350 ms and mapping `phase` to the progress steps.

## Consequences
- Screens can be developed without a backend, and a backend shape change is fixed in one file. A contract test checks the documented response keys against `docs/openapi.json`.
- Polling is simple and robust (no reconnect logic) but coarser than SSE: the three planning steps are reported together because the backend only reports `planning`.
- The adapters must not invent facts. Where the backend does not supply a value (rows lost when the dry run failed, requested quantity) the adapter returns `null` and the UI shows a dash.
- The SSE endpoint still exists and is tested; moving progress to SSE is possible without touching components.

# Security policy

## Reporting a vulnerability

Please report privately using GitHub's **"Report a vulnerability"** (Security tab → Advisories) on this repository. Do not open a public issue. You can expect an acknowledgement within a few days. This is a prototype maintained by a small team, so fixes are best-effort.

## What this project is, security-wise

A local-first demonstration. It is designed to run on `127.0.0.1` and has demo-grade protections. It should not be exposed to an untrusted network as is.

### What exists
- SQL policy guard that blocks `DROP`, `TRUNCATE`, `ALTER` and unscoped `UPDATE`/`DELETE` without explicit approval (unit and fuzz tested).
- Human approval before any change to live data; snapshot-based undo.
- The server binds to loopback by default and warns if it is bound elsewhere without a token.
- Optional shared bearer token (`TT_API_TOKEN`) for every `/api` route except `/api/health`.
- POST requests carrying a non-local `Origin` are rejected (403); CORS is allowed for `localhost`/`127.0.0.1` only.
- Requests get an ID (`X-Request-Id`) and are written to a structured access log. Query strings are not logged.
- Dependency audits (`pip-audit`, `npm audit`) and Dependabot updates run in CI.
- The container runs as a non-root user.

### What does not exist (known gaps)
- **No users, roles or per-person approval.** The audit log records what happened, not who approved it.
- **A single shared token, no rate limiting, no TLS.** Put it behind a reverse proxy that terminates TLS if you must expose it.
- `POST /api/demo/reset` and `/api/admin/sync-stock` are demo endpoints that destroy or rewrite data. They are not meant for a shared deployment.
- The browser UI stores the optional token in `localStorage`, which is readable by any script on the same origin.
- LLM prompts include user text and source code; they are sent to the configured provider (Gemini or Bedrock). Do not point it at code or data you cannot share.
- Sessions are in memory, so approval state is lost on restart; the audit events remain.

## Supported versions

Only the latest `main` is supported.

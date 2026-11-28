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
- POST requests from another site (an `Origin` that is neither allow-listed nor this server itself) are rejected (403); CORS is allowed for `localhost`/`127.0.0.1` only unless `TT_ALLOWED_ORIGINS` is set.
- Per-address token-bucket rate limits (reads, writes, failed-auth lockout), configurable, `429` + `Retry-After`. In process: behind several instances use a shared limiter in front too.
- `Host` header allow-list (automatic while bound to loopback) against DNS rebinding.
- Security headers on every response (CSP, `nosniff`, frame denial, referrer and permissions policies); `no-store` on the API; errors never include stack traces (they carry a request id instead).
- Request bodies are size-capped; stalled connections time out; event streams are capped.
- Requests get an ID (`X-Request-Id`) and are written to a structured access log. Query strings are not logged.
- Dependency audits (`pip-audit`, `npm audit`) and Dependabot updates run in CI.
- The container runs as a non-root user.

### What does not exist (known gaps)
- **No users, roles or per-person approval.** The audit log records what happened, not who approved it.
- **A single shared token and no TLS.** Put it behind a reverse proxy that terminates TLS if you must expose it (and set `TT_TRUST_PROXY=1` so rate limits see real client addresses). Rate limiting is per process.
- `POST /api/demo/reset` and `/api/admin/sync-stock` are demo endpoints that destroy or rewrite data. They are not meant for a shared deployment: set `TT_DEMO_ROUTES=0` to hide `/api/demo/*`.
- The browser UI stores the optional token in `localStorage`, which is readable by any script on the same origin.
- LLM prompts include user text and source code; they are sent to the configured provider (Gemini or Bedrock). Do not point it at code or data you cannot share.
- Sessions are in memory, so approval state is lost on restart; the audit events remain.

## Supported versions

Only the latest `main` is supported.

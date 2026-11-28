# Changelog

All notable changes. Format based on [Keep a Changelog](https://keepachangelog.com/); versions follow `pyproject.toml`.

## [Unreleased]

### Added
- React UI connected to the real backend (`npm run dev:live`, `npm run build:live`), served at `/app/`; `services/adapters.js` translates API JSON and is unit-tested.
- API: `GET /api/audit`, `/api/audit/summary`, `/api/audit/<id>`; `POST /api/session/<id>/discard`; `GET /api/health`; `X-Request-Id` on every response with a structured access log; optional bearer token (`TT_API_TOKEN`); `HOST` setting.
- OpenAPI spec (`docs/openapi.json`) with a contract test against the server.
- Quality gate in CI: ruff, mypy, Python tests with a 75% coverage floor, intent evals, ESLint, frontend unit and Playwright end-to-end tests, dependency audits, Docker build.
- `hamid_bot` workflow that approves low-risk PRs after the gate passes.
- `Dockerfile` and `docker-compose.yml` (non-root, health check, loopback-only port).
- Intent-parser eval set (`evals/`, 24 labelled prompts) with a regression baseline.
- Architecture document with diagrams and six ADRs; `CONTRIBUTING.md`, `SECURITY.md`, `CODEOWNERS`, PR template, Dependabot.
- `pyproject.toml` with extras (`gemini`, `bedrock`, `ai`, `dev`).

### Added (security, rate limiting, QA)
- Rate limiting (token bucket per client address): separate read and write buckets, `429` with `Retry-After` and `X-RateLimit-*` headers, failed-auth lockout, health and static files exempt. All limits are configurable.
- Security headers on every response (CSP, `nosniff`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, COOP), `Cache-Control: no-store` on the API, `WWW-Authenticate` on 401.
- Host-header allow-list (DNS-rebinding defence), configurable CORS/origin allow-list, optional `TT_DEMO_ROUTES=0`.
- `timetravel/config.py`: one validated place for every setting (fails fast, names the bad variable); data dir, allowed origins/hosts, demo SKU and limits are no longer hardcoded.
- Every API error now has `{error, code, request_id}`; database lock/busy errors are `503 DB_BUSY` with `Retry-After`, not a client `400`.
- Frontend API client: per-request timeout, retries for GET only (backoff, honours `Retry-After`), stable error codes (`TIMEOUT`, `NETWORK_ERROR`, `RATE_LIMITED`, `UNAUTHORIZED`, `INVALID_RESPONSE` ...), request id in 5xx messages. Writes are never retried.
- React `ErrorBoundary`: a render error shows a recoverable message instead of a blank page.
- E2E QA suites (`frontend/e2e/qa.spec.js`, `ratelimit.spec.js`): security headers, CSP with no violations, origin/host checks, error shapes, path traversal, UI behaviour when the API returns 429/500/non-JSON or is unreachable, and real rate limiting against a second tightly limited server.

### Added (hardening and durability)
- POST bodies are capped (`413`), must be a JSON object, and a bad `Content-Length` is `400`. Stalled clients time out.
- `/api/.../events` streams are capped (`503` + `Retry-After` when full); the slot is always released.
- Bounded memory: finished sessions are evicted past `TT_MAX_SESSIONS`; the changelog is pruned to `TT_CHANGELOG_MAX_ROWS`.
- Favicon: PNG and Apple touch icons next to the SVG, `theme-color`, and `/favicon.ico` redirects to the SVG.

### Changed
- The React app is the only UI; `/` redirects to `/app/`. The legacy `web/` dashboard was removed.
- The rule-based parser understands "prior to the sync" style phrasing; the console's default prompt now rewinds, keeps orders and fixes the bug.
- `POST` errors: a missing request field is `400` (was a misleading `404 unknown route`); an unknown session is `404 session not found`.
- Repo layout: analysis docs moved to `docs/`, benchmark evidence to `docs/evidence/`, the CLI demo to `scripts/`; the five `requirements-*.txt` files were replaced by `pyproject.toml` extras.
- `IntentResult.preserve` from the fallback parser is now a tuple, as declared.

### Fixed
- Browser `POST`s from the app were refused with 403 whenever it was served from a real domain (only `localhost` origins were accepted). Same-origin requests are now allowed.
- A request whose abort signal had already fired still reached the network; a non-JSON `200` (wrong host, SPA fallback) was silently treated as `null`.
- Unhandled errors return `{"error":"internal error","request_id":...}` and log the traceback instead of leaking `str(exception)`.
- The warm-up thread no longer holds the global DB lock (API requests no longer queue behind it) and logs failures instead of swallowing them.
- The live DB uses SQLite WAL mode (readers no longer block on writers). `seed.reset()` also deletes `-wal`/`-shm` files so a stale one cannot corrupt a fresh database.
- `changelog(ts)` index; `changes_after` uses it (25 ms to 5 ms at 300k rows) and `/api/state` reads `MAX(id)` instead of `COUNT(*)`.
- Blank page on Vercel: the build base is `/` there (it stays `/app/` for the Python server).
- Undo restored an old database snapshot and erased the session's audit events; audit rows are now preserved, even if the code restore fails.
- `/api/state` reported `patched: true` before any fix because `place_order()` already contains `WHERE sku = ?`.
- Approve could be enabled when the merge dry run failed but the patch tests passed.
- A failed apply (plan still actionable) was listed as a terminal failure in the audit log.
- Double-clicking Discard could log twice; it is now atomic.
- A web page on another origin could `POST` to the local API (`/api/demo/reset`); non-local origins now get 403.
- The incident banner stayed up after a rewind-only recovery.
- Removed 10 unused imports and variables; fixed 8 mypy errors.

## [0.1.0]

Hackathon build: SQLite engine with trigger-based change log, rewind on a clone, three-way merge planning, SQL guard, human approval and undo, recovery engine with checksum verification, durable audit events with SSE, LLM layer with regex fallback, benchmarks, and the first UI.

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

### Changed
- The React app is the only UI; `/` redirects to `/app/`. The legacy `web/` dashboard was removed.
- The rule-based parser understands "prior to the sync" style phrasing; the console's default prompt now rewinds, keeps orders and fixes the bug.
- `POST` errors: a missing request field is `400` (was a misleading `404 unknown route`); an unknown session is `404 session not found`.
- Repo layout: analysis docs moved to `docs/`, benchmark evidence to `docs/evidence/`, the CLI demo to `scripts/`; the five `requirements-*.txt` files were replaced by `pyproject.toml` extras.
- `IntentResult.preserve` from the fallback parser is now a tuple, as declared.

### Fixed
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

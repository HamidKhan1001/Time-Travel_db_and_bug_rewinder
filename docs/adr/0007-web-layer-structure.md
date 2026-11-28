# 0007. The HTTP layer is a package with an explicit context and a route table

**Status:** accepted. Supersedes the "single `server.py`" layout implied by ADR 0006.

## Context
`server.py` had grown to 560 lines: routing, security, rate limiting, static files, SSE, background threads and the business routes in one class. `do_GET` had cyclomatic complexity 29, routes were an `if path.startswith(...)` chain, and configuration, limiters and counters were module globals. Tests had to patch module attributes (`server.MAX_BODY_BYTES`, `server.LIMITERS`, `server.SSE_SLOTS`), and the OpenAPI contract test scraped route strings out of the source text.

## Decision
Keep `server.py` as a 5-line entry point and move the implementation to `timetravel/web/`:

- `context.AppContext` holds settings, security, rate limiters, stream slots and warm-up numbers. Nothing in the HTTP layer reads a module global for state.
- `router.Router` is a route table (`method + pattern -> function(Request)`). It is also what the contract test reads, so the code and `docs/openapi.json` are compared exactly.
- `security.Security` does host, origin, CORS, bearer-token and rate-limit decisions from headers and addresses only, so it is unit-tested without sockets.
- `handler.Handler` is one pipeline for every request (admit -> route -> parse body -> run -> write) and the only place that maps exceptions to `{error, code, request_id}`.
- One module per area under `routes/`; `static`, `streaming` and `maintenance` are separate modules.

## Consequences
- Two servers with different settings can run in one process; tests pass settings instead of patching globals (`tests/harness.py`).
- Adding an endpoint is one function plus one `router.get/post` line, and the contract test fails until the spec documents it.
- More files, and a small amount of indirection (`Request`, `Response`, `Stream`) that the old code did not need.
- `http.server` remains: still no HTTP/2 or async (see ADR 0006).
- Still process-local: `agent.SESSIONS` and `db.LOCK` are module-level and shared by every context in the process. Moving them into the context is the next step if more than one app instance per process is ever needed.

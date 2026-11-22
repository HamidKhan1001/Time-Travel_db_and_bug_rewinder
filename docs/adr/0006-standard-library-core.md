# 0006. The core engine uses only the standard library and SQLite

**Status:** accepted.

## Context
The project is a demo that others must be able to run in minutes, and a recovery tool should have a small supply-chain surface.

## Decision
`timetravel/`, `server.py` and the test suite depend only on Python and SQLite. AI provider SDKs (`google-genai`, `boto3`) are optional extras (`pip install ".[gemini]"`). The UI is built with Node but ships as static files served by the same Python process.

## Consequences
- `python3 server.py` works on a clean machine with a built UI, and the Docker image has no third-party Python packages by default.
- `http.server` is used instead of a framework: fine for a local demo, but no HTTP/2, no built-in auth, no async. A production deployment would sit behind a real server or move to ASGI.
- Dependency audits (`pip-audit`, `npm audit`) only have the optional SDKs and the UI toolchain to check.

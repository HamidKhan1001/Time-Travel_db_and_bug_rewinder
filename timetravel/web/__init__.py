"""HTTP layer: a small stdlib server split into single-purpose modules.

    app.py        wiring: build the context, router and server; the process entry point
    context.py    AppContext: configuration, security, rate limiters, stream slots, warm-up state (no module globals)
    handler.py    the socket-facing request handler: one pipeline for every request
    router.py     route table (method + pattern -> function); also the source of truth for the OpenAPI contract test
    security.py   host / origin / CORS checks, bearer auth, rate limiting, security headers (no sockets: unit-testable)
    http.py       Request, Response, Stream types and the error classes routes raise
    static.py     the built React app, safely
    streaming.py  Server-Sent Events plumbing
    maintenance.py  background upkeep (warm-up measurement, changelog pruning)
    routes/       one module per area of the API: health, state, orders, recovery, audit, demo, ui
"""

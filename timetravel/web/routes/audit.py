"""GET /api/audit, /api/audit/summary, /api/audit/{id}: the recovery history, derived from the durable audit log."""
from ... import audit, db
from ..http import BadRequest, NotFound, Request

DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE = 5, 100


def _entries():
    with db.LOCK:
        conn = db.connect()
        try:
            return audit.summarize_recoveries(conn)
        finally:
            conn.close()


def summary(req: Request):
    return audit.recovery_stats(_entries())


def listing(req: Request):
    try:
        page = max(1, int(req.arg("page", "1")))
        size = min(MAX_PAGE_SIZE, max(1, int(req.arg("pageSize", str(DEFAULT_PAGE_SIZE)))))
    except ValueError:
        raise BadRequest("page and pageSize must be integers") from None
    rows = audit.filter_recoveries(_entries(), req.arg("search"), req.arg("status"), req.arg("scenario"))
    start = (page - 1) * size
    return {"items": rows[start:start + size], "total": len(rows), "page": page, "pageSize": size}


def entry(req: Request):
    for e in _entries():
        if e["id"] == req.params["id"]:
            return e
    raise NotFound("recovery not found")


def register(router):
    router.get("/api/audit/summary", summary)          # static before {id}
    router.get("/api/audit", listing)
    router.get("/api/audit/{id}", entry)

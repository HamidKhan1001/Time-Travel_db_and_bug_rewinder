"""Starting a recovery and driving a session: rewind, approve / discard / undo, read it back, its audit trail, its events."""
from ... import agent
from ..http import NotFound, Request
from ..streaming import open_event_stream


def _session(req: Request):
    session = agent.SESSIONS.get(req.params["id"])
    if session is None:
        raise NotFound("session not found")
    return session


def rewind(req: Request):
    return {"id": agent.start(req.json().get("prompt", "")).id}


def _action(name: str):
    def route(req: Request):
        _session(req)                                      # 404 before doing anything
        return getattr(agent, name)(req.params["id"]).to_json()
    route.__name__ = name
    return route


def get_session(req: Request):
    return _session(req).to_json()


def session_audit(req: Request):
    sid = req.params["id"]
    events = agent.audit_events(sid)
    if not events:
        raise NotFound("audit history not found")
    return {"session_id": sid, "events": events}


def session_events(req: Request):
    return open_event_stream(req, req.params["id"])


def register(router):
    router.post("/api/rewind", rewind)
    for action in ("approve", "discard", "undo"):
        router.post("/api/session/{id}/" + action, _action(action))
    router.get("/api/session/{id}/events", session_events)
    router.get("/api/session/{id}/audit", session_audit)
    router.get("/api/session/{id}", get_session)

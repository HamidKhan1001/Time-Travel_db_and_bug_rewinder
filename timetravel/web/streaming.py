"""Server-Sent Events plumbing: validate the request, take a stream slot, hand back a Stream."""
import logging

from .. import agent, sse
from .http import BadRequest, HttpError, NotFound, Request, Stream, Unavailable

log = logging.getLogger("timetravel.http")


def open_event_stream(req: Request, session_id: str) -> Stream:
    """The audit events of one session, replayed from ``Last-Event-ID`` and then followed live."""
    if not sse.validate_session_id(session_id):
        raise BadRequest("invalid session id")
    header_id = req.headers.get("Last-Event-ID")
    query_id = req.arg("last_event_id", None)
    try:
        after_id = sse.parse_last_event_id(header_id if header_id is not None else query_id)
    except ValueError as error:
        raise BadRequest(str(error)) from None
    try:
        history = sse.read_events_after(session_id, after_id)
    except Exception:
        log.exception("request_id=%s could not read audit history for %s", req.request_id, session_id)
        raise HttpError("audit stream unavailable") from None
    if not history and session_id not in agent.SESSIONS:
        raise NotFound("session or audit history not found")
    slots = req.ctx.sse_slots                                   # every stream pins a server thread: cap them
    if not slots.acquire(blocking=False):
        raise Unavailable("too many open event streams, retry shortly", headers={"Retry-After": 5})
    frames = sse.iter_sse_frames(session_id, after_id, closed=req.client_closed)
    return Stream(frames=_with_retry_hint(frames), release=slots.release)


def _with_retry_hint(frames):
    yield "retry: 3000\n\n"
    yield from frames

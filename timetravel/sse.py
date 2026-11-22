"""Server-Sent Events support for the existing SQLite-backed session audit log."""
import json
import re
import sqlite3
import time
from typing import Dict, Iterable, Optional, Tuple

from . import audit, db

SESSION_ID_RE = re.compile(r"^INC-[A-Z0-9]+$")
HEARTBEAT_SECONDS = 15.0
POLL_SECONDS = 0.25
MAX_STREAM_SECONDS = 300.0

EVENT_NAMES = {
    "recovery_initiated": "session_started",
    "recovery_preview_generated": "preview_generated",
    "approval_granted": "approval_granted",
    "approval_rejected": "approval_rejected",
    "recovery_execution_started": "recovery_started",
    "integrity_verified": "integrity_verified",
    "recovery_completed": "recovery_completed",
    "recovery_failed": "recovery_failed",
    "undo_initiated": "undo_started",
    "undo_completed": "undo_completed",
    "undo_failed": "undo_failed",
    "undo_rejected": "undo_failed",
}


def validate_session_id(session_id: str) -> bool:
    return bool(session_id and SESSION_ID_RE.fullmatch(session_id))


def parse_last_event_id(value: Optional[str]) -> int:
    if value is None or value == "":
        return 0
    if not value.isdigit():
        raise ValueError("Last-Event-ID must be a non-negative integer")
    return int(value)


def audit_event_to_sse(record: Dict) -> Tuple[str, str, str]:
    """Convert a durable audit record to (event name, SSE id, JSON frame)."""
    audit_id = str(record["id"])
    event_name = EVENT_NAMES.get(record["event_type"], record["event_type"])
    envelope = {
        "id": record["id"],
        "session_id": record["session_id"],
        "event_type": event_name,
        "timestamp": record["ts"],
        "status": record["status"],
        "payload": record["detail"],
    }
    data = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    frame = f"id: {audit_id}\nevent: {event_name}\ndata: {data}\n\n"
    return event_name, audit_id, frame


def format_heartbeat(timestamp: Optional[float] = None) -> str:
    value = time.time() if timestamp is None else timestamp
    return f": heartbeat {value:.3f}\n\n"


def format_stream_error() -> str:
    return 'event: stream_error\ndata: {"error":"audit stream unavailable"}\n\n'


def read_events_after(session_id: str, after_id: int) -> Iterable[Dict]:
    """Read session-scoped durable audit events without holding a database transaction."""
    with db.LOCK:
        conn = db.connect()
        try:
            return list(audit.read_session_events_after(conn, session_id, after_id))
        finally:
            conn.close()


def iter_sse_frames(
    session_id: str,
    after_id: int,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
    poll_seconds: float = POLL_SECONDS,
    max_seconds: float = MAX_STREAM_SECONDS,
    closed=None,
) -> Iterable[str]:
    """Yield replayed and live audit frames without holding database transactions."""
    cursor = after_id
    try:
        replay_records = read_events_after(session_id, cursor)
    except sqlite3.Error:
        yield format_stream_error()
        return
    for record in replay_records:
        if closed is not None and closed():
            return
        cursor = max(cursor, int(record["id"]))
        yield audit_event_to_sse(record)[2]

    start = time.monotonic()
    heartbeat_at = start + heartbeat_seconds
    while time.monotonic() - start < max_seconds:
        if closed is not None and closed():
            return
        time.sleep(poll_seconds)
        try:
            records = read_events_after(session_id, cursor)
        except sqlite3.Error:
            yield format_stream_error()
            return
        for record in records:
            cursor = max(cursor, int(record["id"]))
            yield audit_event_to_sse(record)[2]
        if time.monotonic() >= heartbeat_at:
            yield format_heartbeat()
            heartbeat_at = time.monotonic() + heartbeat_seconds

"""Durable audit events for legacy demo recovery sessions."""
import json
import sqlite3
import time
from typing import Any, Dict, Iterable, Optional

TABLE = "session_audit_events"
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('started','approved','rejected','completed','failed')),
  ts REAL NOT NULL,
  detail_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_session_audit_session ON {TABLE}(session_id, id);
CREATE INDEX IF NOT EXISTS ix_session_audit_type ON {TABLE}(event_type, id);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the additive audit schema without replacing existing tables."""
    conn.executescript(SCHEMA)


def record_event(
    conn: sqlite3.Connection,
    session_id: str,
    event_type: str,
    status: str,
    detail: Optional[Dict[str, Any]] = None,
) -> int:
    """Persist one audit event; parameterized and explicit about failures."""
    allowed_statuses = {"started", "approved", "rejected", "completed", "failed"}
    if status not in allowed_statuses:
        raise ValueError(f"unsupported audit status: {status}")
    if not session_id or not event_type:
        raise ValueError("session_id and event_type are required")
    detail_json = json.dumps(detail or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    cur = conn.execute(
        f"INSERT INTO {TABLE}(session_id,event_type,status,ts,detail_json) VALUES(?,?,?,?,?)",
        (session_id, event_type, status, time.time(), detail_json),
    )
    return int(cur.lastrowid)


def read_events(conn: sqlite3.Connection) -> Iterable[Dict[str, Any]]:
    rows = conn.execute(
        f"SELECT id,session_id,event_type,status,ts,detail_json FROM {TABLE} ORDER BY id ASC"
    ).fetchall()
    return tuple(_row_to_dict(row) for row in rows)


def read_session_events(conn: sqlite3.Connection, session_id: str) -> Iterable[Dict[str, Any]]:
    rows = conn.execute(
        f"SELECT id,session_id,event_type,status,ts,detail_json FROM {TABLE} "
        "WHERE session_id=? ORDER BY id ASC",
        (session_id,),
    ).fetchall()
    return tuple(_row_to_dict(row) for row in rows)


def read_session_events_after(conn: sqlite3.Connection, session_id: str, after_id: int) -> Iterable[Dict[str, Any]]:
    """Read only a session's audit events after a stable audit ID."""
    if after_id < 0:
        raise ValueError("after_id must be non-negative")
    rows = conn.execute(
        f"SELECT id,session_id,event_type,status,ts,detail_json FROM {TABLE} "
        "WHERE session_id=? AND id>? ORDER BY id ASC",
        (session_id, after_id),
    ).fetchall()
    return tuple(_row_to_dict(row) for row in rows)


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    detail = {}
    try:
        detail = json.loads(row["detail_json"])
    except (TypeError, json.JSONDecodeError):
        detail = {"detail_json_error": "stored detail is not valid JSON"}
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "event_type": row["event_type"],
        "status": row["status"],
        "ts": row["ts"],
        "detail": detail,
    }

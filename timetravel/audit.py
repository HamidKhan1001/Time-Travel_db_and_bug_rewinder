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


def restore_events(conn: sqlite3.Connection, events: Iterable[Dict[str, Any]]) -> None:
    """Put previously read audit events back (same ids) after the live DB was replaced by a snapshot.

    Undo restores a pre-recovery copy of the database, which would otherwise erase the audit rows
    written after that copy was taken, including the record of the recovery being undone.
    """
    ensure_schema(conn)
    conn.executemany(
        f"INSERT OR REPLACE INTO {TABLE}(id,session_id,event_type,status,ts,detail_json) VALUES(?,?,?,?,?,?)",
        [(e["id"], e["session_id"], e["event_type"], e["status"], e["ts"],
          json.dumps(e["detail"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)) for e in events],
    )
    conn.commit()


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


SCENARIO_NAME = "Warehouse Wipe (Stock 0)"
_TERMINAL = {
    "recovery_completed": "applied",
    "undo_completed": "undone",
    "recovery_discarded": "discarded",
    "recovery_failed": "failed",
}


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def summarize_recoveries(conn: sqlite3.Connection) -> list:
    """One record per finished recovery session, newest first, built only from durable audit events.

    Sessions that are still in flight (no terminal event yet) are left out. The latest terminal
    event wins, so a failed apply that is retried and then succeeds is reported as applied.
    """
    sessions: Dict[str, Dict[str, Any]] = {}
    for event in read_events(conn):
        entry = sessions.setdefault(event["session_id"], {
            "id": event["session_id"], "status": None, "startedAt": _iso(event["ts"]), "_started": event["ts"],
            "scenario": SCENARIO_NAME, "prompt": None, "rewindRef": None, "delta": None,
            "rowsLost": None, "risk": None, "durationSec": None,
        })
        detail, kind = event["detail"], event["event_type"]
        if kind == "recovery_initiated":
            entry["prompt"] = detail.get("prompt")
        elif kind == "recovery_preview_generated":
            if detail.get("rewind_target_ts"):
                entry["rewindRef"] = "@" + time.strftime("%H:%M:%S", time.localtime(detail["rewind_target_ts"]))
            entry["delta"] = {
                "kept": detail.get("orders_preserved") or 0,
                "discarded": detail.get("discarded_rows") or 0,
                "conflicts": detail.get("conflict_count") or 0,
            }
            if detail.get("risk_score") is not None:
                entry["risk"] = detail["risk_score"] / 100
        if kind in _TERMINAL:
            entry["status"] = _TERMINAL[kind]
            if kind == "recovery_completed":
                total = (detail.get("timings") or {}).get("total_workflow_seconds")
                entry["durationSec"] = round(total, 1) if total is not None else None
    finished = [e for e in sessions.values() if e["status"]]
    for e in finished:
        e["rowsLost"] = 0 if e["status"] in ("applied", "undone") else None
        e["prompt"] = e["prompt"] or "(prompt not recorded)"
    finished.sort(key=lambda e: e["_started"], reverse=True)
    for e in finished:
        del e["_started"]
    return finished


def filter_recoveries(entries: list, search: str = "", status: str = "", scenario: str = "") -> list:
    query = (search or "").strip().lower()
    out = []
    for e in entries:
        if status and e["status"] != status:
            continue
        if scenario and e["scenario"] != scenario:
            continue
        if query and not any(query in (str(e.get(k) or "")).lower() for k in ("id", "prompt", "scenario", "rewindRef")):
            continue
        out.append(e)
    return out


def recovery_stats(entries: list, target: float = 99) -> dict:
    today = time.strftime("%Y-%m-%d", time.localtime())
    decided = [e for e in entries if e["status"] != "discarded"]
    ok = [e for e in decided if e["status"] != "failed"]
    return {
        "totalRecoveries": len(entries),
        "today": sum(1 for e in entries if e["startedAt"].startswith(today)),
        "successRate": round(len(ok) / len(decided) * 100, 1) if decided else None,
        "targetSuccessRate": target,
    }

"""Read-only access to the durable transaction history."""
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from . import transaction_logger as logger


@dataclass(frozen=True)
class ChangeEvent:
    id: int
    transaction_id: int
    event_seq: int
    ts: float
    tbl: str
    pk: Any
    pk_json: str
    op: str
    old_values: Optional[str]
    new_values: Optional[str]

    def old_row(self) -> Optional[Dict[str, Any]]:
        if self.old_values is None:
            return None
        return json.loads(self.old_values)

    def new_row(self) -> Optional[Dict[str, Any]]:
        if self.new_values is None:
            return None
        return json.loads(self.new_values)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "transaction_id": self.transaction_id,
            "event_seq": self.event_seq,
            "ts": self.ts,
            "tbl": self.tbl,
            "pk": self.pk,
            "pk_json": self.pk_json,
            "op": self.op,
            "old_values": self.old_values,
            "new_values": self.new_values,
        }


@dataclass(frozen=True)
class TransactionRecord:
    id: int
    started_at: float
    source: Optional[str]
    events: Tuple[ChangeEvent, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "started_at": self.started_at,
            "source": self.source,
            "events": [event.as_dict() for event in self.events],
        }


def ensure_history(conn, tables, clock=None):
    return logger.ensure_schema(conn, tables, clock)


def history_installed(conn):
    return logger.history_installed(conn)


def capture_scope(tables):
    return logger.capture_scope(tables)


def _event_from_row(row):
    return ChangeEvent(
        id=row["id"],
        transaction_id=row["transaction_id"],
        event_seq=row["event_seq"],
        ts=row["ts"],
        tbl=row["tbl"],
        pk=row["pk"],
        pk_json=row["pk_json"],
        op=row["op"],
        old_values=row["old_values"],
        new_values=row["new_values"],
    )


def latest_event_id(conn):
    return int(conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM {logger.HISTORY_TABLE}").fetchone()[0])


def fetch_events(conn, after_event_id=0, transaction_id=None, order="id DESC", limit=None):
    """Read captured events. This function never writes."""
    if order not in ("id ASC", "id DESC"):
        raise ValueError("order must be 'id ASC' or 'id DESC'")
    sql = f"SELECT * FROM {logger.HISTORY_TABLE} WHERE id > ?"
    params: List[Any] = [after_event_id]
    if transaction_id is not None:
        sql += " AND transaction_id = ?"
        params.append(transaction_id)
    sql += f" ORDER BY {order}"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return tuple(_event_from_row(row) for row in conn.execute(sql, params))


def fetch_events_after_timestamp(conn, ts, order="id DESC"):
    """Timestamp fallback for compatibility; event ids are preferred for deterministic rewinds."""
    if order not in ("id ASC", "id DESC"):
        raise ValueError("order must be 'id ASC' or 'id DESC'")
    sql = f"SELECT * FROM {logger.HISTORY_TABLE} WHERE ts > ? ORDER BY {order}"
    return tuple(_event_from_row(row) for row in conn.execute(sql, (ts,)))


def fetch_transactions(conn, after_event_id=0):
    """Return captured transactions with events in their original sequence."""
    events = fetch_events(conn, after_event_id=after_event_id, order="id ASC")
    grouped: Dict[int, List[ChangeEvent]] = {}
    for event in events:
        grouped.setdefault(event.transaction_id, []).append(event)
    if not grouped:
        return ()
    placeholders = ",".join("?" * len(grouped))
    rows = conn.execute(
        f"SELECT * FROM {logger.STATE_TABLE} WHERE id IN ({placeholders}) ORDER BY id",
        tuple(grouped)).fetchall()
    return tuple(TransactionRecord(
        id=row["id"],
        started_at=row["started_at"],
        source=row["source"],
        events=tuple(sorted(grouped[row["id"]], key=lambda event: (event.event_seq, event.id))),
    ) for row in rows)

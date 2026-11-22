"""Deterministic recovery analysis. Reads history and plans compensations without writing."""
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from . import change_tracker
from .change_tracker import ChangeEvent
from .dependencies import (
    DependencyEdge,
    ForeignKey,
    build_dependency_graph,
    inspect_foreign_keys,
    order_steps,
    relationship_summary,
)

_COMPENSATION = {"I": "D", "U": "U", "D": "I"}
_MISSING = object()


class UnsupportedChangeError(ValueError):
    pass


@dataclass(frozen=True)
class RecoveryStep:
    event_id: int
    transaction_id: int
    event_seq: int
    ts: float
    source_op: str
    op: str
    tbl: str
    pk: Any
    pk_json: str
    old_values: Optional[str]
    new_values: Optional[str]

    def old_row(self):
        cached = getattr(self, "_old_row_cache", _MISSING)
        if cached is _MISSING:
            cached = json.loads(self.old_values) if self.old_values else None
            object.__setattr__(self, "_old_row_cache", cached)
        return cached

    def new_row(self):
        cached = getattr(self, "_new_row_cache", _MISSING)
        if cached is _MISSING:
            cached = json.loads(self.new_values) if self.new_values else None
            object.__setattr__(self, "_new_row_cache", cached)
        return cached


@dataclass(frozen=True)
class RecoveryPlan:
    anchor_event_id: int
    selection: str
    steps: Tuple[RecoveryStep, ...]
    selected_transaction_ids: Tuple[int, ...] = ()
    foreign_keys: Tuple[ForeignKey, ...] = ()
    dependency_edges: Tuple[DependencyEdge, ...] = ()
    execution_order: Tuple[int, ...] = ()

    @property
    def source_event_ids(self):
        return tuple(step.event_id for step in self.steps)

    @property
    def transaction_ids(self):
        return tuple(dict.fromkeys(step.transaction_id for step in self.steps))

    @property
    def execution_steps(self):
        by_id = {step.event_id: step for step in self.steps}
        order = self.execution_order or self.source_event_ids
        return tuple(by_id[event_id] for event_id in order if event_id in by_id)

    def fingerprint(self):
        cached = getattr(self, "_fingerprint_cache", None)
        if cached is not None:
            return cached
        payload = [[step.event_id, step.transaction_id, step.event_seq, step.source_op, step.op,
                    step.tbl, step.pk_json, step.old_values, step.new_values] for step in self.steps]
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        cached = hashlib.sha256(blob).hexdigest()
        object.__setattr__(self, "_fingerprint_cache", cached)
        return cached


def _step_from_event(event, tables):
    if event.tbl not in tables:
        raise UnsupportedChangeError(f"table {event.tbl} is not covered by the transaction history")
    if event.op not in _COMPENSATION:
        raise UnsupportedChangeError(f"operation {event.op} is not captured by the transaction history")
    if not event.pk_json:
        raise UnsupportedChangeError(f"event {event.id} has no primary key")
    return RecoveryStep(
        event_id=event.id,
        transaction_id=event.transaction_id,
        event_seq=event.event_seq,
        ts=event.ts,
        source_op=event.op,
        op=_COMPENSATION[event.op],
        tbl=event.tbl,
        pk=event.pk,
        pk_json=event.pk_json,
        old_values=event.old_values,
        new_values=event.new_values,
    )


def _scope_events(events, transaction_ids=None, exclude_transaction_ids=None):
    selected = set(transaction_ids) if transaction_ids is not None else None
    excluded = set(exclude_transaction_ids or ())
    return tuple(event for event in events
                 if (selected is None or event.transaction_id in selected) and event.transaction_id not in excluded)


def _finalize_plan(conn, anchor_event_id, selection, events, tables):
    steps = tuple(_step_from_event(event, tables) for event in events)
    scoped = tuple(dict.fromkeys(event.transaction_id for event in events))
    keys = inspect_foreign_keys(conn, tables)
    edges = build_dependency_graph(conn, steps, keys, tables)
    order = order_steps(steps, edges)
    return RecoveryPlan(anchor_event_id=anchor_event_id, selection=selection, steps=steps,
                        selected_transaction_ids=scoped, foreign_keys=keys,
                        dependency_edges=edges, execution_order=order)


def build_plan_after_event(conn, event_id, tables, transaction_ids=None, exclude_transaction_ids=None):
    """Plan the reversal of captured events after `event_id`, optionally limited to transactions."""
    if not change_tracker.history_installed(conn):
        raise RuntimeError("durable transaction history is not installed on this database")
    events = change_tracker.fetch_events(conn, after_event_id=event_id, order="id DESC")
    events = _scope_events(events, transaction_ids, exclude_transaction_ids)
    return _finalize_plan(conn, event_id, "event-id", events, tables)


def build_plan_after_timestamp(conn, ts, tables, transaction_ids=None, exclude_transaction_ids=None):
    """Timestamp compatibility mode. Event-id anchors are preferred for deterministic rewinds."""
    if not change_tracker.history_installed(conn):
        raise RuntimeError("durable transaction history is not installed on this database")
    events = change_tracker.fetch_events_after_timestamp(conn, ts, order="id DESC")
    events = _scope_events(events, transaction_ids, exclude_transaction_ids)
    return _finalize_plan(conn, 0, "timestamp", events, tables)


def explain_plan(plan):
    """Return a deterministic JSON-safe summary of a plan."""
    return {
        "anchor_event_id": plan.anchor_event_id,
        "selection": plan.selection,
        "event_count": len(plan.steps),
        "transaction_count": len(plan.transaction_ids),
        "selected_transaction_ids": list(plan.selected_transaction_ids),
        "fingerprint": plan.fingerprint(),
        "tables": sorted({step.tbl for step in plan.steps}),
        "operations": sorted({step.op for step in plan.steps}),
        "relationships": relationship_summary(plan.foreign_keys),
        "execution_order": list(plan.execution_order or plan.source_event_ids),
        "dependency_edges": [edge.as_dict() for edge in plan.dependency_edges],
    }

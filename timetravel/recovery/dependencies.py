"""Foreign-key discovery and dependency ordering for recovery plans."""
import heapq
import json
from collections import defaultdict
from dataclasses import dataclass


class UnsupportedRelationshipError(ValueError):
    pass


@dataclass(frozen=True)
class ForeignKey:
    child_table: str
    child_column: str
    parent_table: str
    parent_column: str
    on_delete: str
    on_update: str

    def as_dict(self):
        return {
            "child_table": self.child_table,
            "child_column": self.child_column,
            "parent_table": self.parent_table,
            "parent_column": self.parent_column,
            "on_delete": self.on_delete,
            "on_update": self.on_update,
        }


@dataclass(frozen=True)
class DependencyEdge:
    before_event_id: int
    after_event_id: int
    child_table: str
    parent_table: str
    reason: str

    def as_dict(self):
        return {
            "before_event_id": self.before_event_id,
            "after_event_id": self.after_event_id,
            "child_table": self.child_table,
            "parent_table": self.parent_table,
            "reason": self.reason,
        }


def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def row_key(table, pk):
    return table, _canonical(pk)


def _columns(conn, table):
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({_quote(table)})")]


def inspect_foreign_keys(conn, tables):
    """Return supported single-column foreign keys between captured tables."""
    keys = []
    for table in sorted(tables):
        grouped = defaultdict(list)
        for row in conn.execute(f"PRAGMA foreign_key_list({_quote(table)})"):
            grouped[row["id"]].append(row)
        for group_id in sorted(grouped):
            rows = grouped[group_id]
            if len(rows) != 1:
                raise UnsupportedRelationshipError(
                    f"multi-column foreign key {group_id} on {table} is not supported")
            row = rows[0]
            parent_table = row["table"]
            child_column = row["from"]
            parent_column = row["to"] or tables.get(parent_table)
            if parent_table not in tables:
                raise UnsupportedRelationshipError(
                    f"foreign key {table}.{child_column} targets uncaptured table {parent_table}")
            if parent_table == table:
                raise UnsupportedRelationshipError(
                    f"self-referential foreign key on {table} is not supported")
            if not child_column or not parent_column:
                raise UnsupportedRelationshipError(
                    f"foreign key {group_id} on {table} does not expose single columns")
            if parent_column != tables[parent_table]:
                raise UnsupportedRelationshipError(
                    f"foreign key {table}.{child_column} targets non-primary-key {parent_table}.{parent_column}")
            child_columns = _columns(conn, table)
            parent_columns = _columns(conn, parent_table)
            if child_column not in child_columns or parent_column not in parent_columns:
                raise UnsupportedRelationshipError(
                    f"foreign key {table}.{child_column} -> {parent_table}.{parent_column} has a missing column")
            keys.append(ForeignKey(
                child_table=table,
                child_column=child_column,
                parent_table=parent_table,
                parent_column=parent_column,
                on_delete=(row["on_delete"] or "NO ACTION").upper(),
                on_update=(row["on_update"] or "NO ACTION").upper(),
            ))
    return tuple(keys)


def relationship_summary(keys):
    return {
        "relationships": [key.as_dict() for key in keys],
        "parent_tables": sorted({key.parent_table for key in keys}),
        "child_tables": sorted({key.child_table for key in keys}),
    }


def _step_row(step):
    return step.old_row() if step.op in ("I", "U") else step.new_row()


def _assert_no_primary_key_change(step, tables, row=None):
    if step.op != "U":
        return
    if row is None:
        row = _step_row(step)
    if row is None:
        return
    old_pk = row.get(tables[step.tbl])
    if old_pk is not None and _canonical(old_pk) != _canonical(step.pk):
        raise UnsupportedRelationshipError(
            f"primary-key-changing update on {step.tbl} is not supported for FK-aware recovery")


def _current_child_rows(conn, key, parent_pk, table_pks):
    pk_column = table_pks[key.child_table]
    return [dict(row) for row in conn.execute(
        f"SELECT {_quote(pk_column)} AS pk, {_quote(key.child_column)} AS fk_value "
        f"FROM {_quote(key.child_table)} WHERE {_quote(key.child_column)} = ?", (parent_pk,))]


def build_dependency_graph(conn, steps, keys, table_pks):
    """Build ordered edges between affected records from declared foreign keys."""
    steps_by_key = defaultdict(list)
    step_rows = {step.event_id: _step_row(step) for step in steps}
    for step in steps:
        _assert_no_primary_key_change(step, table_pks, step_rows[step.event_id])
        steps_by_key[row_key(step.tbl, step.pk)].append(step)

    edges = set()
    for step in steps:
        row = step_rows[step.event_id]
        if step.op in ("I", "U") and row is not None:
            for key in keys:
                if key.child_table != step.tbl:
                    continue
                value = row.get(key.child_column)
                if value is None:
                    continue
                parent_steps = steps_by_key.get(row_key(key.parent_table, value), ())
                for parent_step in parent_steps:
                    if parent_step.event_id == step.event_id or parent_step.op not in ("I", "U"):
                        continue
                    reason = "restore-parent-before-child" if step.op == "I" else "update-parent-before-child"
                    edges.add((parent_step.event_id, step.event_id, key.child_table, key.parent_table, reason))
        elif step.op == "D":
            for key in keys:
                if key.parent_table != step.tbl:
                    continue
                for child_row in _current_child_rows(conn, key, step.pk, table_pks):
                    child_steps = steps_by_key.get(row_key(key.child_table, child_row["pk"]), ())
                    for child_step in child_steps:
                        if child_step.event_id == step.event_id:
                            continue
                        if child_step.op == "D":
                            reason = "remove-child-before-parent"
                        elif child_step.op == "U":
                            target = step_rows.get(child_step.event_id) or {}
                            if _canonical(target.get(key.child_column)) == _canonical(step.pk):
                                continue
                            reason = "repoint-child-before-parent"
                        else:
                            continue
                        edges.add((child_step.event_id, step.event_id, key.child_table, key.parent_table, reason))
    return tuple(DependencyEdge(*edge) for edge in sorted(edges))


def order_steps(steps, edges):
    """Topologically order steps, preserving captured order when no dependency applies."""
    by_id = {step.event_id: step for step in steps}
    index = {step.event_id: position for position, step in enumerate(steps)}
    successors = defaultdict(list)
    indegree = {step.event_id: 0 for step in steps}
    for edge in edges:
        if edge.before_event_id not in by_id or edge.after_event_id not in by_id:
            raise UnsupportedRelationshipError("dependency edge references an event outside the plan")
        successors[edge.before_event_id].append(edge.after_event_id)
        indegree[edge.after_event_id] += 1
    ready = [(index[event_id], event_id) for event_id, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    ordered = []
    while ready:
        _, event_id = heapq.heappop(ready)
        ordered.append(event_id)
        for next_id in successors[event_id]:
            indegree[next_id] -= 1
            if indegree[next_id] == 0:
                heapq.heappush(ready, (index[next_id], next_id))
    if len(ordered) != len(steps):
        raise UnsupportedRelationshipError("dependency cycle in recovery plan")
    return tuple(ordered)

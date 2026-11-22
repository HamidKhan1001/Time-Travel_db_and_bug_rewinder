"""Integrity validation for recovery plans and recovered database state."""
import json
from . import dependencies, verification
from .recovery_planner import RecoveryPlan


class RecoveryConflictError(RuntimeError):
    def __init__(self, conflicts):
        self.conflicts = conflicts
        detail = "; ".join(conflict["detail"] for conflict in conflicts)
        super().__init__("Recovery conflict: " + detail)


def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _check(name, ok, detail):
    return {"name": name, "ok": bool(ok), "detail": detail}


def _canonical(value):
    def normalize(item):
        if isinstance(item, float):
            return float(format(item, ".15g"))
        if isinstance(item, list):
            return [normalize(child) for child in item]
        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items()}
        return item

    return json.dumps(normalize(value), sort_keys=True, separators=(",", ":"), default=str)


def _columns(conn, table):
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({_quote(table)})")]


def _row_by_pk(conn, table, pk_column, pk_value):
    row = conn.execute(
        f"SELECT * FROM {_quote(table)} WHERE {_quote(pk_column)} = ?", (pk_value,)).fetchone()
    return dict(row) if row is not None else None


def _unique_indexes(conn, table):
    indexes = []
    for index in conn.execute(f"PRAGMA index_list({_quote(table)})"):
        if not index["unique"]:
            continue
        columns = tuple(row["name"] for row in conn.execute(f"PRAGMA index_info({_quote(index['name'])})"))
        if columns:
            indexes.append(columns)
    return indexes


def _conflict(kind, step, detail, expected=None, actual=None):
    return {
        "kind": kind,
        "event_id": step.event_id,
        "transaction_id": step.transaction_id,
        "tbl": step.tbl,
        "pk": step.pk,
        "pk_json": step.pk_json,
        "detail": detail,
        "expected": expected,
        "actual": actual,
    }


def _expected_states(plan):
    expected = {}
    for step in sorted(plan.steps, key=lambda item: item.event_id):
        key = (step.tbl, step.pk_json)
        if step.source_op == "I":
            # INSERT captured by the faulty transaction; compensation is DELETE.
            expected[key] = (step, None)
        elif step.source_op == "U":
            # UPDATE compensation restores OLD values.
            expected[key] = (step, step.old_row())
        else:
            # DELETE compensation restores the deleted row.
            expected[key] = (step, step.old_row())
    return expected


def validate_plan(plan, tables):
    """Validate a plan structurally without touching the database."""
    checks = []
    ids = [step.event_id for step in plan.steps]
    checks.append(_check("Plan events are strictly newest-first", ids == sorted(ids, reverse=True),
                         f"{len(ids)} step(s)"))
    checks.append(_check("Plan steps use captured tables", all(step.tbl in tables for step in plan.steps),
                         f"{len({step.tbl for step in plan.steps})} table(s)"))
    checks.append(_check("Plan steps use supported operations",
                         all(step.op in ("I", "U", "D") for step in plan.steps),
                         ",".join(sorted({step.op for step in plan.steps})) or "none"))
    value_errors = 0
    for step in plan.steps:
        if step.source_op == "I" and not (step.op == "D" and step.new_values is not None):
            value_errors += 1
        elif step.source_op == "U" and not (step.op == "U" and step.old_values and step.new_values):
            value_errors += 1
        elif step.source_op == "D" and not (step.op == "I" and step.old_values and step.new_values is None):
            value_errors += 1
    checks.append(_check("Plan values match captured operations", value_errors == 0,
                         f"{value_errors} malformed step(s)"))
    fingerprint = plan.fingerprint()
    checks.append(_check("Plan has a stable fingerprint", len(fingerprint) == 64, fingerprint[:12]))
    order = plan.execution_order or plan.source_event_ids
    checks.append(_check("Dependency order covers every step",
                         sorted(order) == sorted(plan.source_event_ids),
                         f"{len(order)} ordered / {len(plan.steps)} steps"))
    ids = set(plan.source_event_ids)
    index = {event_id: position for position, event_id in enumerate(order)}
    valid_edges = all(edge.before_event_id in ids and edge.after_event_id in ids
                      and index[edge.before_event_id] < index[edge.after_event_id]
                      for edge in plan.dependency_edges)
    checks.append(_check("Dependency edges are acyclic and ordered", valid_edges,
                         f"{len(plan.dependency_edges)} edge(s)"))
    return checks


def assert_plan_valid(plan, tables):
    checks = validate_plan(plan, tables)
    failed = [check["name"] for check in checks if not check["ok"]]
    if failed:
        raise ValueError("Invalid recovery plan: " + "; ".join(failed))
    return checks


def validate_step_schema(conn, plan, tables):
    """Ensure every identifier in a plan exists in the live schema."""
    bad_identifiers = 0
    bad_values = 0
    columns_by_table = {}
    parsed_payloads = {}
    parse_error = object()
    for step in plan.steps:
        if step.tbl not in tables:
            bad_identifiers += 1
            continue
        columns = columns_by_table.get(step.tbl)
        if columns is None:
            columns = set(_columns(conn, step.tbl))
            columns_by_table[step.tbl] = columns
        if tables[step.tbl] not in columns:
            bad_identifiers += 1
        for payload in (step.old_values, step.new_values):
            if payload is None:
                continue
            if payload not in parsed_payloads:
                try:
                    parsed_payloads[payload] = json.loads(payload)
                except (TypeError, ValueError):
                    parsed_payloads[payload] = parse_error
            row = parsed_payloads[payload]
            if row is parse_error:
                bad_values += 1
                continue
            if not isinstance(row, dict) or not set(row).issubset(columns):
                bad_identifiers += 1
    return [
        _check("Plan identifiers exist in live schema", bad_identifiers == 0,
               f"{bad_identifiers} unsafe identifier(s)"),
        _check("Plan row values are valid JSON", bad_values == 0, f"{bad_values} malformed payload(s)"),
    ]


def _target_row(step):
    return step.old_row() if step.op in ("I", "U") else step.new_row()


def _parent_available(conn, key, value, tables, restored):
    if value is None:
        return True
    if _row_by_pk(conn, key.parent_table, tables[key.parent_table], value) is not None:
        return True
    return dependencies.row_key(key.parent_table, value) in restored


def analyze_foreign_key_conflicts(conn, plan, tables, keys):
    """Detect orphan references and unsafe parent deletes before execution."""
    conflicts = []
    restored = {dependencies.row_key(step.tbl, step.pk) for step in plan.steps if step.op == "I"}
    removed = {dependencies.row_key(step.tbl, step.pk) for step in plan.steps if step.op == "D"}
    updates = {dependencies.row_key(step.tbl, step.pk): _target_row(step)
               for step in plan.steps if step.op == "U"}

    for step in plan.steps:
        if step.op not in ("I", "U"):
            continue
        row = _target_row(step)
        if row is None:
            continue
        for key in keys:
            if key.child_table != step.tbl:
                continue
            value = row.get(key.child_column)
            if _parent_available(conn, key, value, tables, restored):
                continue
            conflicts.append(_conflict(
                "missing-parent-reference", step,
                f"{step.tbl}.{key.child_column} references missing {key.parent_table} {_canonical(value)}",
                row.get(key.child_column), None))

    for step in plan.steps:
        if step.op != "D":
            continue
        for key in keys:
            if key.parent_table != step.tbl:
                continue
            pk_column = tables[key.child_table]
            children = conn.execute(
                f"SELECT {_quote(pk_column)} AS pk FROM {_quote(key.child_table)} "
                f"WHERE {_quote(key.child_column)} = ?", (step.pk,)).fetchall()
            for child in children:
                child_key = dependencies.row_key(key.child_table, child["pk"])
                if child_key in removed:
                    continue
                target = updates.get(child_key)
                if target is not None and _canonical(target.get(key.child_column)) != _canonical(step.pk):
                    continue
                action = key.on_delete.upper()
                if action == "CASCADE":
                    kind = "cascade-child-loss"
                    detail = f"deleting {step.tbl} {step.pk_json} would cascade-delete {key.child_table} {child['pk']}"
                elif action in ("SET NULL", "SET DEFAULT"):
                    kind = "dependent-child-loss"
                    detail = f"deleting {step.tbl} {step.pk_json} would alter {key.child_table} {child['pk']} via {action}"
                else:
                    kind = "dependent-rows-exist"
                    detail = f"{key.child_table} {child['pk']} still references {step.tbl} {step.pk_json}"
                conflicts.append(_conflict(kind, step, detail, None, child_key[1]))
    return conflicts


def analyze_conflicts(conn, plan, tables, keys=None):
    """Compare the plan's compensated target states with the database before writes."""
    conflicts = []
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        conflicts.append({
            "kind": "foreign-key-violation",
            "event_id": 0,
            "transaction_id": 0,
            "tbl": "",
            "pk": None,
            "pk_json": "",
            "detail": f"database already has {len(violations)} foreign key violation(s)",
            "expected": None,
            "actual": None,
        })

    for step in plan.steps:
        table = step.tbl
        pk_json = step.pk_json
        actual_row = _row_by_pk(conn, table, tables[table], step.pk)

        if step.source_op == "I":
            if actual_row is None:
                continue
            captured_row = step.new_row()
            if captured_row is not None and _canonical(actual_row) == _canonical(captured_row):
                continue
            conflicts.append(_conflict(
                "duplicate-primary-key", step,
                f"{table} {pk_json} is present with a different or later value; recovery would overwrite it",
                captured_row, actual_row))

        elif step.source_op == "U":
            captured_row = step.new_row()
            if actual_row is None:
                conflicts.append(_conflict(
                    "missing-record", step,
                    f"{table} {pk_json} is missing; recovery cannot restore it safely",
                    step.old_row(), None))
            elif captured_row is not None and _canonical(actual_row) != _canonical(captured_row):
                if _canonical(actual_row) == _canonical(step.old_row()):
                    continue
                conflicts.append(_conflict(
                    "conflicting-change", step,
                    f"{table} {pk_json} changed after the captured event",
                    step.old_row(), actual_row))

        else:
            target_row = step.old_row()
            if actual_row is not None:
                if target_row is not None and _canonical(actual_row) == _canonical(target_row):
                    continue
                conflicts.append(_conflict(
                    "duplicate-primary-key", step,
                    f"{table} {pk_json} already exists; recovery would overwrite it",
                    target_row, actual_row))

    written = [step for step in plan.steps if step.op in ("I", "U")]
    unique_by_table = {}
    for step in written:
        target_row = step.old_row()
        table = step.tbl
        pk_column = tables[table]
        target_pk = target_row[pk_column]
        if table not in unique_by_table:
            unique_by_table[table] = _unique_indexes(conn, table)
        unique_sets = [(pk_column,)] + unique_by_table[table]
        for columns in unique_sets:
            values = [target_row.get(column) for column in columns]
            if any(value is None for value in values):
                continue
            where = " AND ".join(f"{_quote(column)} IS ?" for column in columns)
            rows = conn.execute(
                f"SELECT {_quote(pk_column)} AS pk FROM {_quote(table)} WHERE {where}", values).fetchall()
            for row in rows:
                if _canonical(row["pk"]) != _canonical(target_pk):
                    conflicts.append(_conflict(
                        "unique-constraint", step,
                        f"{table} unique value {values} is held by another row",
                        target_row, row["pk"]))
    if keys is None:
        keys = dependencies.inspect_foreign_keys(conn, tables)
    conflicts.extend(analyze_foreign_key_conflicts(conn, plan, tables, keys))
    return conflicts


def verify_foreign_keys(conn, keys=None):
    """Verify every declared relationship plus SQLite's own foreign-key check."""
    if keys is None:
        keys = dependencies.inspect_foreign_keys(conn, {})
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    checks = [_check("All foreign-key constraints valid", not violations, f"{len(violations)} violations")]
    for key in keys:
        orphans = conn.execute(
            f"SELECT COUNT(*) FROM {_quote(key.child_table)} AS c "
            f"LEFT JOIN {_quote(key.parent_table)} AS p "
            f"ON c.{_quote(key.child_column)} = p.{_quote(key.parent_column)} "
            f"WHERE c.{_quote(key.child_column)} IS NOT NULL AND p.{_quote(key.parent_column)} IS NULL").fetchone()[0]
        checks.append(_check(
            f"{key.child_table}.{key.child_column} -> {key.parent_table}.{key.parent_column}",
            orphans == 0, f"{orphans} orphan(s)"))
    return checks


def verify_state(conn, expected_stock=None, preserved_ids=None, tables=None, keys=None):
    """Validate post-recovery state with the same check shape as the existing tools."""
    fk_checks = verify_foreign_keys(conn, keys)
    checks = [_check("Foreign keys intact", fk_checks[0]["ok"], fk_checks[0]["detail"])]
    checks.extend(fk_checks[1:])
    if tables is None or "inventory" in tables:
        negative = conn.execute("SELECT COUNT(*) FROM inventory WHERE stock < 0").fetchone()[0]
        checks.append(_check("No negative stock", negative == 0, f"{negative} negative rows"))
    if expected_stock:
        got = {row["sku"]: row["stock"] for row in conn.execute("SELECT sku, stock FROM inventory")}
        bad = sum(1 for sku, stock in expected_stock.items() if got.get(sku) != stock)
        checks.append(_check("Inventory matches expected state", bad == 0, f"{bad} mismatched SKUs"))
    if preserved_ids:
        placeholders = ",".join("?" * len(preserved_ids))
        present = conn.execute(
            f"SELECT COUNT(*) FROM orders WHERE id IN ({placeholders})", tuple(preserved_ids)).fetchone()[0]
        checks.append(_check("Preserved orders present", present == len(preserved_ids),
                             f"{present}/{len(preserved_ids)} present"))
    return checks


def checksum(conn, tables):
    """Deterministic digest of all captured business-table rows."""
    return verification.checksum_database(conn, tables)

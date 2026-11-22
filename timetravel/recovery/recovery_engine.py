"""Deterministic recovery execution. Plans are produced by recovery_planner only."""
import os
import time

from .. import db
from . import dependencies, integrity, verification
from .integrity import RecoveryConflictError
from .recovery_planner import RecoveryPlan, build_plan_after_event, build_plan_after_timestamp


def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _apply_step(conn, step, tables):
    pk_column = tables[step.tbl]
    table = _quote(step.tbl)
    pk_field = _quote(pk_column)
    if step.op == "D":
        cur = conn.execute(f"DELETE FROM {table} WHERE {pk_field} = ?", (step.pk,))
        expected = "D"
    elif step.op == "U":
        old = step.old_row()
        if pk_column not in old:
            raise ValueError(f"update event {step.event_id} does not contain its primary key")
        columns = list(old)
        assignments = ",".join(f"{_quote(column)} = ?" for column in columns)
        cur = conn.execute(
            f"UPDATE {table} SET {assignments} WHERE {pk_field} = ?",
            [old[column] for column in columns] + [step.pk])
        expected = "U"
    elif step.op == "I":
        old = step.old_row()
        columns = list(old)
        placeholders = ",".join("?" * len(columns))
        cur = conn.execute(
            f"INSERT INTO {table}({','.join(_quote(column) for column in columns)}) VALUES({placeholders})",
            [old[column] for column in columns])
        expected = "I"
    else:
        raise ValueError(f"unsupported compensating operation: {step.op}")
    if cur.rowcount != 1:
        raise RuntimeError(f"recovery step {step.event_id} changed {cur.rowcount} rows, expected 1 ({expected})")


def create_plan(conn, tables=None, anchor_event_id=None, target_ts=None,
                transaction_ids=None, exclude_transaction_ids=None):
    """Analyze history and return a deterministic plan without writing."""
    tables = tables or db.TABLES
    if anchor_event_id is not None:
        return build_plan_after_event(conn, anchor_event_id, tables, transaction_ids, exclude_transaction_ids)
    if target_ts is not None:
        return build_plan_after_timestamp(conn, target_ts, tables, transaction_ids, exclude_transaction_ids)
    raise ValueError("provide anchor_event_id or target_ts")


def _simulate_plan(conn, plan, tables, keys):
    clone = db.clone(conn, ":memory:")
    baseline = None
    try:
        clone.execute("BEGIN IMMEDIATE")
        for step in plan.execution_steps:
            _apply_step(clone, step, tables)
        checks = integrity.verify_state(clone, tables=tables, keys=keys)
        baseline = verification.build_baseline(clone, tables, label="expected-recovery")
        clone.execute("ROLLBACK")
        return checks, baseline
    except Exception as error:
        if baseline is not None:
            baseline.close()
        if clone.in_transaction:
            clone.execute("ROLLBACK")
        return [{"name": "Recovery dry run", "ok": False, "detail": str(error)}], None
    finally:
        clone.close()


def _start_run(conn, plan):
    cur = conn.execute(
        "INSERT INTO recovery_runs(started_at, plan_fingerprint, anchor_event_id, selection, step_count, status) "
        "VALUES(?, ?, ?, ?, ?, 'started')",
        (db.clock.now(), plan.fingerprint(), plan.anchor_event_id, plan.selection, len(plan.steps)))
    return int(cur.lastrowid)


_ACTION_SQL = (
    "INSERT INTO recovery_actions(run_id, source_event_id, transaction_id, op, tbl, pk_json, status, ts) "
    "VALUES(?, ?, ?, ?, ?, ?, ?, ?)")


def _record_actions(conn, run_id, steps, status):
    if not steps:
        return
    ts = db.clock.now()
    conn.executemany(_ACTION_SQL, [
        (run_id, step.event_id, step.transaction_id, step.op, step.tbl, step.pk_json, status, ts)
        for step in steps])


def _record_action(conn, run_id, step, status):
    _record_actions(conn, run_id, (step,), status)


def _record_failed_actions(conn, run_id, plan):
    _record_actions(conn, run_id, plan.steps, "failed")


def _finish_run(conn, run_id, status, detail):
    conn.execute(
        "UPDATE recovery_runs SET finished_at = ?, status = ?, detail = ? WHERE id = ?",
        (db.clock.now(), status, detail, run_id))


def execute_plan(conn, plan, tables=None, verify=True, reference=None, timing=None):
    """Validate, audit, verify, and apply a recovery plan atomically in one transaction."""
    started = time.perf_counter()
    tables = tables or db.TABLES
    if conn.in_transaction:
        raise RuntimeError("execute_plan requires a connection outside an explicit transaction")
    plan_checks = integrity.assert_plan_valid(plan, tables)
    schema_checks = integrity.validate_step_schema(conn, plan, tables)
    keys = dependencies.inspect_foreign_keys(conn, tables)
    failed_schema = [check["name"] for check in schema_checks if not check["ok"]]
    if failed_schema:
        raise ValueError("Unsafe recovery plan: " + "; ".join(failed_schema))

    conflicts = integrity.analyze_conflicts(conn, plan, tables, keys)
    if conflicts:
        raise RecoveryConflictError(conflicts)
    preflight_end = time.perf_counter()
    if timing is not None:
        timing["preflight_seconds"] = preflight_end - started

    simulation, simulation_reference = _simulate_plan(conn, plan, tables, keys)
    simulation_end = time.perf_counter()
    if timing is not None:
        timing["simulation_seconds"] = simulation_end - preflight_end
    failed_simulation = [check for check in simulation if not check["ok"]]
    if failed_simulation:
        if simulation_reference is not None:
            simulation_reference.close()
        raise RecoveryConflictError([{
            "kind": "simulation-failure",
            "event_id": 0,
            "transaction_id": 0,
            "tbl": "",
            "pk": None,
            "pk_json": "",
            "detail": check["detail"],
            "expected": None,
            "actual": None,
        } for check in failed_simulation])

    owns_reference = reference is None
    if reference is None:
        reference = simulation_reference
    verification_report = None
    run_id = _start_run(conn, plan)
    apply_start = time.perf_counter()
    applied_steps = []
    try:
        conn.execute("BEGIN IMMEDIATE")
        for step in plan.execution_steps:
            _apply_step(conn, step, tables)
            applied_steps.append(step)
        _record_actions(conn, run_id, applied_steps, "applied")
        apply_end = time.perf_counter()
        if timing is not None:
            timing["apply_seconds"] = apply_end - apply_start
        checks = integrity.verify_state(conn, tables=tables, keys=keys) if verify else []
        verification_start = time.perf_counter()
        verification_report = verification.verify_state_against(conn, reference, tables=tables)
        verification_end = time.perf_counter()
        if timing is not None:
            timing["checksum_verification_seconds"] = verification_end - verification_start
        verified = verification_report["integrity_status"] == "VERIFIED"
        detail = (f"{verification_report['matching_rows']}/{verification_report['total_rows_checked']} rows verified; "
                  f"missing={verification_report['missing_rows']}, "
                  f"unexpected={verification_report['unexpected_rows']}, "
                  f"modified={verification_report['mismatching_rows']}")
        checks.append({"name": "Checksum verification", "ok": verified, "detail": detail})
        failed = [check["name"] for check in checks if not check["ok"]]
        if failed:
            raise RuntimeError("post-recovery checks failed: " + "; ".join(failed))
        conn.execute("COMMIT")
        if timing is not None:
            timing["commit_seconds"] = time.perf_counter() - verification_end
    except Exception as error:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        _finish_run(conn, run_id, "rolled-back", str(error))
        _record_failed_actions(conn, run_id, plan)
        raise
    finally:
        if simulation_reference is not None and simulation_reference is not reference:
            simulation_reference.close()
        if owns_reference and reference is not None:
            reference.close()
    _finish_run(conn, run_id, "committed", "ok")
    if timing is not None:
        timing["execute_plan_seconds"] = time.perf_counter() - started
    return {
        "fingerprint": plan.fingerprint(),
        "steps_applied": len(plan.steps),
        "plan_checks": plan_checks,
        "schema_checks": schema_checks,
        "simulation": simulation,
        "foreign_keys": [key.as_dict() for key in keys],
        "execution_order": list(plan.execution_order or plan.source_event_ids),
        "verification": verification_report,
        "audit_run_id": run_id,
        "checks": checks,
    }


def dry_run_plan(conn, plan, tables=None, dest_path=":memory:"):
    """Execute a plan on a disposable clone; the source connection is never written."""
    tables = tables or db.TABLES
    branch = db.clone(conn, dest_path)
    try:
        return execute_plan(branch, plan, tables=tables)
    finally:
        branch.close()
        if dest_path != ":memory:" and os.path.exists(dest_path):
            os.remove(dest_path)


def snapshot(conn, path):
    """Create a durable pre-recovery database snapshot."""
    clone = db.clone(conn, path)
    clone.close()
    return path


def restore_snapshot(conn, path):
    """Restore a validated snapshot into an idle connection."""
    if conn.in_transaction:
        raise RuntimeError("restore_snapshot requires a connection outside an explicit transaction")
    source = db.connect(path)
    try:
        source.backup(conn)
    finally:
        source.close()
    return path

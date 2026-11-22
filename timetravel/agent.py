"""Orchestrator: parses the request, drives the tools, streams events, enforces the HITL gate."""
import os
import re
import threading
import time
import uuid

from . import audit, db, llm, recovery_projection, tools

PACE = float(os.getenv("TT_PACE", "0.4"))     # tiny pause between steps so the feed is readable on stage
SESSIONS = {}
_monotonic = time.perf_counter


def _elapsed(started, ended):
    return max(0.0, ended - started)


def fmt(ts):
    return time.strftime("%H:%M:%S", time.localtime(ts))


def parse_intent(prompt):
    """LLM-first intent parser with deterministic regex fallback. Always returns a dict."""
    return llm.parse_intent(prompt)


class Session:
    def __init__(self, prompt):
        self.id = "INC-" + uuid.uuid4().hex[:6].upper()
        self.prompt, self.phase, self.events = prompt, "starting", []
        self.parsed = self.branch = self.delta = self.plan = self.patch = self.result = self.timeline = None
        self.recovery_preview = None
        self.actual_recovery = None
        self.verification = None
        self.undo_state = recovery_projection.initial_undo_state()
        self.internal = {}
        self.created = time.time()
        self._workflow_started = _monotonic()
        self._approval_accepted = None
        self._execution_started = None
        self._workflow_finished = None
        self.timings = {
            "planning_preview_seconds": None,
            "approval_delay_seconds": None,
            "recovery_execution_seconds": None,
            "verification_seconds": None,
            "undo_seconds": None,
            "total_workflow_seconds": None,
        }

    def timing_report(self):
        report = dict(self.timings)
        if self._approval_accepted is not None and self._execution_started is not None:
            report["approval_delay_seconds"] = _elapsed(self._approval_accepted, self._execution_started)
        if self._workflow_started is not None and self._workflow_finished is not None:
            report["total_workflow_seconds"] = _elapsed(self._workflow_started, self._workflow_finished)
        return report

    def log(self, agent, msg, level="info"):
        self.events.append({"t": time.time(), "agent": agent, "msg": msg, "level": level})
        time.sleep(PACE)

    def to_json(self):
        patch = dict(self.patch) if self.patch else None
        if patch:
            patch.pop("patched_source", None)
        return {"id": self.id, "prompt": self.prompt, "phase": self.phase, "events": self.events,
                "parsed": self.parsed, "branch": self.branch, "timeline": self.timeline,
                "delta": ({"post_crash": self.delta["post_crash"], "pre_crash": self.delta["pre_crash"],
                           "orders": [{"id": o["id"], "customer_id": o["customer_id"], "total_cents": o["total_cents"],
                                       "created_at": o["created_at"], "phase": o["phase"],
                                       "items": [(i["sku"], i["qty"]) for i in o["items"]]}
                                      for o in self.delta["orders"]]} if self.delta else None),
                "plan": self.plan, "patch": patch, "result": self.result,
                "recovery_preview": self.recovery_preview,
                "actual_recovery": self.actual_recovery,
                "verification": self.verification,
                "undo_state": self.undo_state,
                "timings": self.timing_report(),
                "can_approve": self.phase == "awaiting_approval", "can_undo": self.phase == "applied"}


def start(prompt, background=True):
    s = Session(prompt)
    SESSIONS[s.id] = s
    _record_audit(s, "recovery_initiated", "started", {"prompt_length": len(prompt), "prompt": prompt[:500]})
    if background:
        threading.Thread(target=_run, args=(s,), daemon=True).start()
    else:
        _run(s)
    return s


def _run(s):
    try:
        _pipeline(s)
    except Exception as e:
        s.phase = "error"
        s._workflow_finished = _monotonic()
        s.log("Orchestrator", f"Aborted safely, production untouched: {e}", "error")
        try:
            _record_audit(s, "recovery_failed", "failed", {"detail": str(e), "timings": s.timing_report()})
        except Exception as audit_error:
            s.log("Audit", f"Audit persistence failed: {audit_error}", "error")


def _pipeline(s):
    live = db.connect()
    now = db.clock.now()
    # ---- 1. Orchestrator: parse
    s.phase = "parsing"
    s.log("Orchestrator", f"Incident session {s.id} opened (immutable ID). Parsing request...")
    s.parsed = parse_intent(s.prompt)
    confidence = s.parsed.get("confidence", 1.0)
    if confidence < llm.config.min_confidence:
        s.log(
            "Orchestrator",
            f"⚠ Low confidence ({confidence:.0%}) parsing your request: "
            f"\"{s.parsed.get('reasoning', '')}\". "
            f"Proceeding — review parsed values before approving.",
            "warn",
        )
    incident = tools.detect_incident(live)
    target = None
    if s.parsed["rewind_seconds"]:
        target = now - s.parsed["rewind_seconds"]
    elif s.parsed["before_incident"] and incident:
        target = incident["ts"] - 1
    if target is None:
        raise ValueError("Could not find a rewind point in the request (try 'back to 2 minutes ago').")
    if incident:
        s.log("Orchestrator", f"Incident detected in query log at {fmt(incident['ts'])}: unscoped write touched "
                              f"{incident['rows_affected']:,} rows.", "warn")
        if target >= incident["ts"]:       # deterministic guardrail on the requested time
            s.log("Guardrails", f"Requested rewind point {fmt(target)} is AFTER the incident. "
                                f"Snapping to 1s before the crash ({fmt(incident['ts'] - 1)}).", "warn")
            target = incident["ts"] - 1
    s.parsed.update({"target_ts": target, "incident_ts": incident["ts"] if incident else None,
                     "remediate": s.parsed["remediate"]})
    s.log("Orchestrator", f"Parsed -> rewind to {fmt(target)} (T-{now - target:.0f}s) | preserve: "
                          f"{', '.join(s.parsed['preserve']) or 'nothing'} | code fix: {'yes' if s.parsed['remediate'] else 'no'}")
    s.timeline = {"target": target, "incident": incident["ts"] if incident else None, "now": now}

    # ---- 2. Ephemeral branch
    s.phase = "branching"
    branch_path = os.path.join(db.DATA, f"branch_{s.id}.db")
    branch, stats = tools.rewind_branch_tool(live, target, branch_path)
    s.branch = stats
    s.internal["branch"] = branch
    s.log("Data Reconciler", f"Shadow branch created in {stats['ms']} ms. Reversed {stats['events_reversed']:,} "
                             f"logged changes; branch has {stats['inventory_rows']:,} SKUs, {stats['units']:,} units "
                             f"in stock. Production untouched.")

    # ---- 3. Delta
    s.phase = "extracting_delta"
    delta = tools.extract_delta_tool(live, target, incident["ts"] if incident else None)
    s.delta = delta
    ids = ", ".join(f"#{o['id']}" for o in delta["orders"][-6:])
    s.log("Data Reconciler", f"Post-rewind delta: {len(delta['orders'])} orders "
                             f"({delta['pre_crash']} before crash, {delta['post_crash']} after). Latest: {ids}")
    if s.parsed["preserve_count"] and s.parsed["preserve_count"] != delta["post_crash"]:
        s.log("Orchestrator", f"Note: you said {s.parsed['preserve_count']} orders but I found "
                              f"{delta['post_crash']} after the crash. Preserving all {len(delta['orders'])} since "
                              f"dropping paid orders would be data loss.", "warn")

    # ---- 4. Merge plan
    s.phase = "planning"
    s.log("Data Reconciler", "Running 3-way merge: base (rewound) x live (broken) x delta (new orders). "
                             "Checking foreign keys, idempotency keys, ID collisions, oversells...")
    planning_started = _monotonic()
    plan, expected, summary = tools.plan_merge_tool(
        live, branch, delta, os.path.join(db.DATA, f"scratch_{s.id}.db"))
    s.plan = summary
    s.internal.update(plan=plan, expected=expected)
    s.recovery_preview = recovery_projection.build_preview(live, plan, summary)
    s.timings["planning_preview_seconds"] = _elapsed(planning_started, _monotonic())
    s.log("Data Reconciler", f"Plan: restore {summary['restored_rows']:,} inventory rows, preserve "
                             f"{summary['orders_preserved']} orders, {len(summary['conflicts'])} conflict(s) resolved. "
                             f"Dry run on clone: {'PASSED' if summary['dry_run_ok'] else 'FAILED'}.",
          "ok" if summary["dry_run_ok"] else "error")
    for c in summary["conflicts"]:
        s.log("Data Reconciler", c.get("reason", c["detail"]), "warn")

    # ---- 5. Root cause + patch
    if s.parsed["remediate"]:
        s.phase = "diagnosing"
        s.log("Investigator", "Correlating query log with source code...")
        patch = tools.diagnose_and_patch_tool(live, branch, incident)
        s.patch = patch
        if patch.get("found"):
            g = patch["guard_verdict"]
            s.log("Guardrails", f"Offending statement would be {'ALLOWED' if g['allowed'] else 'BLOCKED'} by policy "
                                f"[{g['rule']}]: {g['why']}", "warn" if not g["allowed"] else "info")
            s.log("Investigator", patch["explanation"])
            if patch.get("diff"):
                s.log("Investigator", "Patch verified on a throwaway clone: " +
                      "; ".join(f"{'PASS' if t['ok'] else 'FAIL'} {t['name']}" for t in patch["tests"]),
                      "ok" if patch["patch_ok"] else "error")
        else:
            s.log("Investigator", patch["explanation"], "warn")

    # ---- 6. HITL gate
    s.internal["live_marker"] = summary["live_marker"]
    s.phase = "awaiting_approval"
    s.log("HITL Gate", f"PAUSED before touching production. Risk {summary['risk']['label']} "
                       f"({summary['risk']['score']}/100). Review the merge and patch, then approve.", "gate")
    _record_audit(s, "recovery_preview_generated", "started", {
        "dry_run_ok": bool(summary.get("dry_run_ok")),
        "restored_rows": summary.get("restored_rows"),
        "orders_preserved": summary.get("orders_preserved"),
        "conflict_count": len(summary.get("conflicts", [])),
        "risk_score": summary.get("risk", {}).get("score"),
        "discarded_rows": summary.get("zero_before"),
        "rewind_target_ts": target,
        "timings": s.timing_report(),
    })
    try:
        branch.close()
    except Exception:
        pass
    live.close()


def approve(sid):
    s = SESSIONS[sid]
    if s.phase != "awaiting_approval":
        _record_audit(s, "approval_rejected", "rejected", {"current_phase": s.phase})
        raise ValueError(f"Session is '{s.phase}', not awaiting approval.")
    approval_accepted = _monotonic()
    s._approval_accepted = approval_accepted
    s.phase = "applying"
    _record_audit(s, "approval_granted", "approved", {"risk_score": s.plan.get("risk", {}).get("score")})
    _record_audit(s, "recovery_execution_started", "started", {"live_marker": s.internal.get("live_marker")})
    s.log("HITL Gate", "Human approved. Starting atomic cutover.", "ok")
    with db.LOCK:
        live = db.connect()
        apply_timing = {}
        execution_started = _monotonic()
        s._execution_started = execution_started
        try:
            patched = s.patch["patched_source"] if s.patch and s.patch.get("patch_ok") else None
            checks = tools.apply_recovery_tool(
                live, s.internal["plan"], s.internal["expected"], s.plan["order_ids"], s.internal["live_marker"],
                patched, os.path.join(db.DATA, f"backup_{s.id}.db"), os.path.join(db.DATA, f"backup_{s.id}.py"),
                timing=apply_timing)
            s.timings["recovery_execution_seconds"] = _elapsed(execution_started, _monotonic())
            s.timings["verification_seconds"] = apply_timing.get("verification_seconds")
            actual = recovery_projection.capture_actual(live, s.recovery_preview)
        except Exception as e:
            if s.timings["recovery_execution_seconds"] is None:
                s.timings["recovery_execution_seconds"] = _elapsed(execution_started, _monotonic())
            s.timings["verification_seconds"] = apply_timing.get("verification_seconds")
            s.phase = "awaiting_approval"
            s.log("Apply", f"Cutover rolled back, production unchanged: {e}", "error")
            _record_audit(s, "recovery_failed", "failed", {"detail": str(e), "timings": s.timing_report()})
            raise
        finally:
            live.close()
    s.result = {"checks": checks, "code_patched": bool(patched)}
    s.phase = "applied"
    s.actual_recovery = actual
    s.verification = recovery_projection.build_verification(checks)
    s.undo_state = {
        "available": True,
        "initiated": False,
        "succeeded": False,
        "failed": False,
        "detail": "Pre-recovery snapshot is available.",
        "completed_at": None,
    }
    s._workflow_finished = _monotonic()
    _record_audit(s, "integrity_verified", "completed", {
        "all_checks_passed": all(c.get("ok") for c in checks),
        "check_count": len(checks),
        "timings": s.timing_report(),
    })
    _record_audit(s, "recovery_completed", "completed", {
        "code_patched": bool(patched),
        "checks": [{"name": c.get("name"), "ok": c.get("ok"), "detail": c.get("detail")} for c in checks],
        "timings": s.timing_report(),
    })
    for c in checks:
        s.log("Smoke Test", f"{'PASS' if c['ok'] else 'FAIL'}: {c['name']} ({c['detail']})", "ok" if c["ok"] else "error")
    s.log("Apply", "Live. Inventory restored, orders preserved" + (", bug patched." if patched else "."), "ok")
    return s


def discard(sid):
    """Reject a plan that is waiting for approval. Production is never touched."""
    s = SESSIONS[sid]
    if s.phase != "awaiting_approval":
        _record_audit(s, "approval_rejected", "rejected", {"current_phase": s.phase})
        raise ValueError(f"Session is '{s.phase}', not awaiting approval.")
    s.phase = "discarded"
    s._workflow_finished = _monotonic()
    _record_audit(s, "recovery_discarded", "rejected", {"timings": s.timing_report()})
    s.log("HITL Gate", "Plan discarded by a human. Production was not touched.", "warn")
    for name in (f"branch_{s.id}.db", f"scratch_{s.id}.db"):
        try:
            os.remove(os.path.join(db.DATA, name))
        except OSError:
            pass
    return s


def undo(sid):
    s = SESSIONS[sid]
    if s.phase != "applied":
        _record_audit(s, "undo_rejected", "rejected", {"current_phase": s.phase})
        raise ValueError("Nothing to undo.")
    _record_audit(s, "undo_initiated", "started", {})
    s.undo_state = {
        "available": False,
        "initiated": True,
        "succeeded": False,
        "failed": False,
        "detail": "Undo accepted; restoring the pre-recovery snapshot.",
        "completed_at": None,
    }
    with db.LOCK:
        live = db.connect()
        undo_started = _monotonic()
        saved_audit = list(audit.read_events(live))   # the snapshot restore below would roll the audit log back too
        try:
            tools.undo_recovery(live, os.path.join(db.DATA, f"backup_{s.id}.db"), os.path.join(db.DATA, f"backup_{s.id}.py"))
            audit.restore_events(live, saved_audit)
            s.timings["undo_seconds"] = _elapsed(undo_started, _monotonic())
        except Exception as e:
            s.timings["undo_seconds"] = _elapsed(undo_started, _monotonic())
            s.undo_state = {
                "available": True,
                "initiated": True,
                "succeeded": False,
                "failed": True,
                "detail": f"Undo failed: {e}",
                "completed_at": time.time(),
            }
            _record_audit(s, "undo_failed", "failed", {"detail": str(e), "timings": s.timing_report()})
            raise
        finally:
            live.close()
    s.phase = "undone"
    s.undo_state = {
        "available": False,
        "initiated": True,
        "succeeded": True,
        "failed": False,
        "detail": "Pre-recovery database snapshot and source backup restored.",
        "completed_at": time.time(),
    }
    _record_audit(s, "undo_completed", "completed", {"timings": s.timing_report()})
    s.log("Apply", "Rewound the rewind: pre-recovery database snapshot and original code restored.", "warn")
    return s


def _record_audit(s, event_type, status, detail=None):
    """Persist a session lifecycle event or raise explicitly on audit failure."""
    with db.LOCK:
        conn = db.connect()
        try:
            audit.record_event(conn, s.id, event_type, status, detail)
        finally:
            conn.close()


def audit_events(sid):
    """Read durable audit events for a session from SQLite."""
    with db.LOCK:
        conn = db.connect()
        try:
            return list(audit.read_session_events(conn, sid))
        finally:
            conn.close()

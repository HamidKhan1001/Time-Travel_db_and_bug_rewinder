"""Orchestrator: parses the request, drives the tools, streams events, enforces the HITL gate."""
import os
import re
import threading
import time
import uuid

from . import db, tools

PACE = float(os.getenv("TT_PACE", "0.4"))     # tiny pause between steps so the feed is readable on stage
SESSIONS = {}
_UNITS = {"second": 1, "sec": 1, "s": 1, "minute": 60, "min": 60, "m": 60, "hour": 3600, "hr": 3600, "h": 3600}


def fmt(ts):
    return time.strftime("%H:%M:%S", time.localtime(ts))


def parse_intent(prompt):
    """Deterministic intent parser (regex). Swap for a Bedrock/Strands LLM call; keep this as fallback."""
    p = prompt.lower()
    out = {"rewind_seconds": None, "before_incident": False, "preserve": [], "preserve_count": None, "remediate": False}
    m = re.search(r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|[smh])\b\s*(?:ago|earlier)?", p)
    if m:
        out["rewind_seconds"] = float(m.group(1)) * _UNITS[m.group(2).rstrip("s") if m.group(2) not in ("s",) else "s"]
    if re.search(r"before the (crash|incident|wipe|bug)", p):
        out["before_incident"] = True
    m = re.search(r"keep (?:the |all )?(\d+)?\s*(orders?|customers?)", p)
    if m:
        out["preserve"].append("orders" if m.group(2).startswith("order") else "customers")
        out["preserve_count"] = int(m.group(1)) if m.group(1) else None
    if re.search(r"\b(fix|patch|repair)\b", p):
        out["remediate"] = True
    return out


class Session:
    def __init__(self, prompt):
        self.id = "INC-" + uuid.uuid4().hex[:6].upper()
        self.prompt, self.phase, self.events = prompt, "starting", []
        self.parsed = self.branch = self.delta = self.plan = self.patch = self.result = self.timeline = None
        self.internal = {}
        self.created = time.time()

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
                "can_approve": self.phase == "awaiting_approval", "can_undo": self.phase == "applied"}


def start(prompt, background=True):
    s = Session(prompt)
    SESSIONS[s.id] = s
    if background:
        threading.Thread(target=_run, args=(s,), daemon=True).start()
    else:
        _run(s)
    return s


def _run(s):
    try:
        _pipeline(s)
    except Exception as e:      # surface failures in the UI instead of dying silently
        s.phase = "error"
        s.log("Orchestrator", f"Aborted safely, production untouched: {e}", "error")


def _pipeline(s):
    live = db.connect()
    now = db.clock.now()
    # ---- 1. Orchestrator: parse
    s.phase = "parsing"
    s.log("Orchestrator", f"Incident session {s.id} opened (immutable ID). Parsing request...")
    s.parsed = parse_intent(s.prompt)
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
    plan, expected, summary = tools.plan_merge_tool(
        live, branch, delta, os.path.join(db.DATA, f"scratch_{s.id}.db"))
    s.plan = summary
    s.internal.update(plan=plan, expected=expected)
    s.log("Data Reconciler", f"Plan: restore {summary['restored_rows']:,} inventory rows, preserve "
                             f"{summary['orders_preserved']} orders, {len(summary['conflicts'])} conflict(s) resolved. "
                             f"Dry run on clone: {'PASSED' if summary['dry_run_ok'] else 'FAILED'}.",
          "ok" if summary["dry_run_ok"] else "error")
    for c in summary["conflicts"]:
        s.log("Data Reconciler", c["detail"], "warn")

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
    live.close()


def approve(sid):
    s = SESSIONS[sid]
    if s.phase != "awaiting_approval":
        raise ValueError(f"Session is '{s.phase}', not awaiting approval.")
    s.phase = "applying"
    s.log("HITL Gate", "Human approved. Starting atomic cutover.", "ok")
    with db.LOCK:
        live = db.connect()
        try:
            patched = s.patch["patched_source"] if s.patch and s.patch.get("patch_ok") else None
            checks = tools.apply_recovery_tool(
                live, s.internal["plan"], s.internal["expected"], s.plan["order_ids"], s.internal["live_marker"],
                patched, os.path.join(db.DATA, f"backup_{s.id}.db"), os.path.join(db.DATA, f"backup_{s.id}.py"))
        except Exception as e:
            s.phase = "awaiting_approval"
            s.log("Apply", f"Cutover rolled back, production unchanged: {e}", "error")
            raise
        finally:
            live.close()
    s.result = {"checks": checks, "code_patched": bool(patched)}
    s.phase = "applied"
    for c in checks:
        s.log("Smoke Test", f"{'PASS' if c['ok'] else 'FAIL'}: {c['name']} ({c['detail']})", "ok" if c["ok"] else "error")
    s.log("Apply", "Live. Inventory restored, orders preserved" + (", bug patched." if patched else "."), "ok")
    return s


def undo(sid):
    s = SESSIONS[sid]
    if s.phase != "applied":
        raise ValueError("Nothing to undo.")
    with db.LOCK:
        live = db.connect()
        tools.undo_recovery(live, os.path.join(db.DATA, f"backup_{s.id}.db"), os.path.join(db.DATA, f"backup_{s.id}.py"))
        live.close()
    s.phase = "undone"
    s.log("Apply", "Rewound the rewind: pre-recovery database snapshot and original code restored.", "warn")
    return s

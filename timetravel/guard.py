"""Deterministic SQL safety guardrails. No LLM involved: these rules cannot hallucinate."""
import re

_DESTRUCTIVE = re.compile(r"\b(DROP|TRUNCATE|ALTER|ATTACH|DETACH)\b", re.I)
_WHERE = re.compile(r"\bWHERE\b", re.I)


def analyze(sql, approved=False):
    s = sql.strip().rstrip(";")
    if ";" in s:
        return {"allowed": False, "rule": "multi-statement", "sql": sql,
                "why": "Multiple statements in one call are never allowed."}
    if _DESTRUCTIVE.search(s):
        return {"allowed": False, "rule": "destructive-ddl", "sql": sql,
                "why": "DROP/TRUNCATE/ALTER are blocked for agents."}
    kind = s.split()[0].upper() if s else ""
    if kind in ("UPDATE", "DELETE") and not _WHERE.search(s):
        if approved:
            return {"allowed": True, "rule": "unscoped-approved", "sql": sql,
                    "why": "Unscoped write allowed by explicit human approval."}
        return {"allowed": False, "rule": "unscoped-write", "sql": sql,
                "why": f"{kind} without WHERE would touch every row. Needs explicit human approval."}
    return {"allowed": True, "rule": "scoped", "sql": sql, "why": "Scoped / idempotent statement."}


def is_unscoped(sql):
    return not analyze(sql)["allowed"]

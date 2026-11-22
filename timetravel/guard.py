"""Deterministic SQL safety guardrails. No LLM involved: these rules cannot hallucinate."""
import re

_DESTRUCTIVE = re.compile(r"\b(DROP|TRUNCATE|ALTER|ATTACH|DETACH)\b", re.I)
_WHERE = re.compile(r"\bWHERE\b", re.I)
_UPDATE_DELETE = re.compile(r"\b(UPDATE|DELETE)\b", re.I)


def _mask_sql(sql):
    """Return SQL with comments and quoted text masked as spaces.

    Masking prevents comments and string/identifier literals from disguising
    destructive keywords, UPDATE/DELETE statements, semicolons, or WHERE clauses.
    """
    out = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]

        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            out.extend("  ")
            i += 2
            while i < n and sql[i] not in "\r\n":
                out.append(" ")
                i += 1
            continue

        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            out.extend("  ")
            i += 2
            while i < n:
                if i + 1 < n and sql[i] == "*" and sql[i + 1] == "/":
                    out.extend("  ")
                    i += 2
                    break
                out.append("\n" if sql[i] in "\r\n" else " ")
                i += 1
            continue

        if ch in ("'", '"', '`'):
            quote = ch
            out.append(" ")
            i += 1
            while i < n:
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:
                        out.extend("  ")
                        i += 2
                        continue
                    out.append(" ")
                    i += 1
                    break
                out.append("\n" if sql[i] in "\r\n" else " ")
                i += 1
            continue

        if ch == "[":
            out.append(" ")
            i += 1
            while i < n:
                if sql[i] == "]":
                    out.append(" ")
                    i += 1
                    break
                out.append(" ")
                i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def analyze(sql, approved=False):
    if not isinstance(sql, str):
        sql = str(sql)

    masked = _mask_sql(sql)
    clean = masked.strip()

    # Reject actual semicolons outside quoted text/comments. A single trailing
    # semicolon is one statement and remains allowed.
    if ";" in clean:
        without_trailing = clean[:-1].rstrip() if clean.endswith(";") else clean
        if ";" in without_trailing:
            return {"allowed": False, "rule": "multi-statement", "sql": sql,
                    "why": "Multiple statements in one call are never allowed."}
        clean = without_trailing

    if _DESTRUCTIVE.search(clean):
        return {"allowed": False, "rule": "destructive-ddl", "sql": sql,
                "why": "DROP/TRUNCATE/ALTER are blocked for agents."}

    kind = clean.split()[0].upper() if clean else ""
    has_update_delete = _UPDATE_DELETE.search(clean)

    if kind in ("UPDATE", "DELETE") or (kind == "WITH" and has_update_delete):
        if not _WHERE.search(clean):
            if approved:
                return {"allowed": True, "rule": "unscoped-approved", "sql": sql,
                        "why": "Unscoped write allowed by explicit human approval."}
            return {"allowed": False, "rule": "unscoped-write", "sql": sql,
                    "why": f"{kind if kind in ('UPDATE', 'DELETE') else 'UPDATE/DELETE'} without WHERE would touch every row. Needs explicit human approval."}

    return {"allowed": True, "rule": "scoped", "sql": sql, "why": "Scoped / idempotent statement."}


def is_unscoped(sql):
    return not analyze(sql)["allowed"]

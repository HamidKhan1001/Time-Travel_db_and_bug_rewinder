"""Deterministic SQL safety guardrails. No LLM involved: these rules cannot hallucinate."""
import re

_DESTRUCTIVE = re.compile(r"\b(DROP|TRUNCATE|ALTER|ATTACH|DETACH)\b", re.I)
_WHERE = re.compile(r"\bWHERE\b", re.I)
_WRITE = re.compile(r"\b(UPDATE|DELETE)\b", re.I)


def _mask_sql(sql):
    """Mask comments and quoted text so they cannot disguise executable SQL."""
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


def _has_balanced_parentheses(sql):
    depth = 0
    for ch in sql:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _top_level_where(sql):
    """Detect a top-level WHERE clause containing an expression."""
    depth = 0
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "(":
            depth += 1
            i += 1
        elif ch == ")":
            depth = max(0, depth - 1)
            i += 1
        elif depth == 0:
            match = _WHERE.match(sql, i)
            if match:
                before = sql[i - 1] if i > 0 else " "
                after = sql[match.end()] if match.end() < len(sql) else " "
                if (before.isspace() or before in "(,;") and (after.isspace() or after in "(,;"):
                    remainder = sql[match.end():].strip().rstrip(";").strip()
                    if remainder:
                        return True
            i += 1
        else:
            i += 1
    return False


def _final_write_statement(sql):
    """Find the final top-level UPDATE or DELETE in direct SQL or a CTE."""
    depth = 0
    found = None
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "(":
            depth += 1
            i += 1
        elif ch == ")":
            depth = max(0, depth - 1)
            i += 1
        elif depth == 0:
            match = _WRITE.match(sql, i)
            if match:
                before = sql[i - 1] if i > 0 else " "
                after = sql[match.end()] if match.end() < len(sql) else " "
                if (before.isspace() or before in "(,;") and (after.isspace() or after in "(,;"):
                    found = (match.group(1).upper(), i)
            i += 1
        else:
            i += 1
    return found


def analyze(sql, approved=False):
    if not isinstance(sql, str):
        sql = str(sql)

    normalized = "".join(" " if ch.isspace() and ch not in "\r\n" else ch for ch in sql)
    masked = _mask_sql(normalized)
    clean = masked.strip()

    if not clean:
        return {"allowed": True, "rule": "scoped", "sql": sql,
                "why": "Scoped / idempotent statement."}

    if ";" in clean:
        without_trailing = clean[:-1].rstrip() if clean.endswith(";") else clean
        if ";" in without_trailing:
            return {"allowed": False, "rule": "multi-statement", "sql": sql,
                    "why": "Multiple statements in one call are never allowed."}
        clean = without_trailing

    if not _has_balanced_parentheses(clean):
        return {"allowed": False, "rule": "malformed-sql", "sql": sql,
                "why": "Malformed SQL with unbalanced parentheses is blocked."}

    if _DESTRUCTIVE.search(clean):
        return {"allowed": False, "rule": "destructive-ddl", "sql": sql,
                "why": "DROP/TRUNCATE/ALTER are blocked for agents."}

    kind = clean.split()[0].upper() if clean else ""
    loose_write = re.match(r"(?i)^(UPDATE|DELETE)[A-Za-z_]", clean)
    if loose_write:
        return {"allowed": False, "rule": "malformed-sql", "sql": sql,
                "why": "Malformed UPDATE/DELETE without SQL keyword boundaries is blocked."}

    write = _final_write_statement(clean)

    if kind in ("UPDATE", "DELETE"):
        write_kind = kind
        write_start = 0
    elif kind == "WITH" and write:
        write_kind, write_start = write
    elif kind == "WITH" and not write and _WRITE.search(clean):
        return {"allowed": False, "rule": "malformed-sql", "sql": sql,
                "why": "Unsupported or malformed CTE write is blocked."}
    else:
        write_kind = None
        write_start = 0

    if write_kind:
        write_sql = clean[write_start:].strip()
        if write_kind == "UPDATE" and not re.search(r"\bSET\b", write_sql, re.I):
            return {"allowed": False, "rule": "malformed-sql", "sql": sql,
                    "why": "Malformed UPDATE without SET is blocked."}
        if write_kind == "DELETE" and not re.search(r"\bFROM\b", write_sql, re.I):
            return {"allowed": False, "rule": "malformed-sql", "sql": sql,
                    "why": "Malformed DELETE without FROM is blocked."}

        if not _top_level_where(write_sql):
            if approved:
                return {"allowed": True, "rule": "unscoped-approved", "sql": sql,
                        "why": "Unscoped write allowed by explicit human approval."}
            return {"allowed": False, "rule": "unscoped-write", "sql": sql,
                    "why": f"{write_kind} without WHERE would touch every row. Needs explicit human approval."}

    return {"allowed": True, "rule": "scoped", "sql": sql, "why": "Scoped / idempotent statement."}


def is_unscoped(sql):
    return not analyze(sql)["allowed"]

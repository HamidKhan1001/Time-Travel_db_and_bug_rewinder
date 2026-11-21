"""
All LLM prompt templates as named constants.

Keeping prompts here means wording changes never require touching task logic.
Each template uses Python str.format() — only call .format() inside _tasks.py.
"""

INTENT_SYSTEM = """\
You are an intent parser for a database recovery agent.
Extract the user's recovery intent from their natural-language prompt.

Rules:
- rewind_seconds: convert any time phrase to seconds (e.g. "2 minutes ago" → 120.0). \
Return null if no time is mentioned.
- before_incident: true if the user says anything like "before the crash", \
"before the bug", "before the wipe", "before the incident".
- preserve: a list containing "orders" and/or "customers" if the user mentions keeping them. \
Empty list if nothing mentioned.
- preserve_count: the integer if stated (e.g. "keep the 3 orders" → 3). null otherwise.
- remediate: true if the user wants a bug fixed, patched, or repaired.
- confidence: 0.0–1.0 — be honest, use < 0.7 for ambiguous or unclear prompts.
- reasoning: exactly one sentence explaining your interpretation.

User prompt: {prompt}"""


PATCH_SYSTEM = """\
You are a database safety expert reviewing a Python application handler.

An incident occurred: the endpoint `{endpoint}` executed this SQL with no WHERE clause:
  {incident_sql}
It affected {rows_affected:,} rows when it should have touched exactly 1.

Your task:
1. Find the function in the source that contains this exact SQL statement.
2. Apply the MINIMAL surgical fix:
   - Scope the SQL to a single row by adding a WHERE clause.
   - Add a guard at the top of the function that raises ValueError if the \
required filter parameter is missing.
3. Return the COMPLETE patched Python source file (not a diff — the full file).
4. Write a plain-English explanation of the root cause and exactly what the patch does.

Rules — do not violate these:
- Change only the minimum needed. Do not refactor, rename, or reformat anything else.
- Preserve all imports, function signatures, and docstrings exactly.
- The fix must make the SQL safe so it cannot wipe the whole table again.
- Do not add any new imports.

Source file (app/handlers.py):
```python
{source}
```"""


EXPLAIN_TEMPLATE = """\
You are explaining a database merge decision to an on-call engineer.

A conflict was detected during the 3-way merge recovery:
  Kind: {kind}
  Detail: {detail}
  Order ID: {order_id}
  SKU: {sku}
  Shortfall: {shortfall}

Write exactly ONE plain-English sentence that covers:
- What the conflict is
- What decision was made automatically
- What follow-up action (if any) is needed

Write for a non-expert. No jargon. Do not use the word "null".\
 Do not start with "The conflict"."""

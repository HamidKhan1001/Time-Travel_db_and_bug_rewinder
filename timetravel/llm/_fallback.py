"""
Deterministic regex intent parser — the original parse_intent logic from agent.py,
extracted into its own module so it is independently testable and clearly separated
from the LLM path.

This is the safety net: it must never fail under any input.
"""
from __future__ import annotations

import re

from ._tasks import IntentResult

_UNITS: dict[str, int] = {
    "second": 1, "sec": 1, "s": 1,
    "minute": 60, "min": 60, "m": 60,
    "hour": 3600, "hr": 3600, "h": 3600,
}

_TIME_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*"
    r"(seconds?|secs?|minutes?|mins?|hours?|hrs?|[smh])"
    r"\b\s*(?:ago|earlier)?",
)
_INCIDENT_RE = re.compile(r"before the (crash|incident|wipe|bug)")
_PRESERVE_RE = re.compile(r"keep (?:the |all )?(\d+)?\s*(orders?|customers?)")
_REMEDIATE_RE = re.compile(r"\b(fix|patch|repair)\b")


def parse_intent_regex(prompt: str) -> IntentResult:
    """
    Deterministic regex parser. Always returns a valid IntentResult.
    confidence is set to 0.9 (not 1.0) to honestly reflect that regex
    is less flexible than an LLM and may miss unusual phrasings.
    """
    p = prompt.lower()

    # --- rewind_seconds ---
    rewind_seconds: float | None = None
    m = _TIME_RE.search(p)
    if m:
        raw_unit = m.group(2)
        # Normalise: strip trailing 's' unless the unit is bare 's'
        unit_key = raw_unit.rstrip("s") if raw_unit not in ("s",) else "s"
        rewind_seconds = float(m.group(1)) * _UNITS.get(unit_key, 1)

    # --- before_incident ---
    before_incident = bool(_INCIDENT_RE.search(p))

    # --- preserve / preserve_count ---
    preserve: list[str] = []
    preserve_count: int | None = None
    m2 = _PRESERVE_RE.search(p)
    if m2:
        preserve.append("orders" if m2.group(2).startswith("order") else "customers")
        preserve_count = int(m2.group(1)) if m2.group(1) else None

    # --- remediate ---
    remediate = bool(_REMEDIATE_RE.search(p))

    return IntentResult(
        rewind_seconds=rewind_seconds,
        before_incident=before_incident,
        preserve=preserve,
        preserve_count=preserve_count,
        remediate=remediate,
        confidence=0.9,
        reasoning="Parsed via deterministic regex (LLM unavailable or fell back).",
        source="regex",
    )

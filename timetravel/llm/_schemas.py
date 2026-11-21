"""
JSON schemas for LLM structured output + validators.

Schemas use standard JSON Schema format (lowercase types) so they work with
both Gemini's responseSchema and Bedrock's Tool Use input_schema.

Validators are the final correctness gate: they run on every LLM response
regardless of provider, catching bad shapes before they reach business logic.
"""
from __future__ import annotations

from typing import Any


# ── Schemas ────────────────────────────────────────────────────────────────────

INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "rewind_seconds", "before_incident", "preserve",
        "preserve_count", "remediate", "confidence", "reasoning",
    ],
    "properties": {
        "rewind_seconds":  {
            "description": "Seconds to rewind (e.g. 120.0 for '2 minutes ago'), or null if not mentioned.",
        },
        "before_incident": {
            "type": "boolean",
            "description": "True if the user said 'before the crash / incident / wipe / bug'.",
        },
        "preserve": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Items to preserve, e.g. ['orders'] or ['orders', 'customers'].",
        },
        "preserve_count": {
            "description": "Integer count if stated ('keep the 3 orders' → 3), else null.",
        },
        "remediate": {
            "type": "boolean",
            "description": "True if the user wants the bug fixed / patched / repaired.",
        },
        "confidence": {
            "type": "number",
            "description": "0.0–1.0 confidence in this interpretation. Use < 0.7 for ambiguous prompts.",
        },
        "reasoning": {
            "type": "string",
            "description": "One sentence explaining your interpretation.",
        },
    },
}

PATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["patched_source", "explanation", "confidence"],
    "properties": {
        "patched_source": {
            "type": "string",
            "description": "Complete patched Python source file (not a diff).",
        },
        "explanation": {
            "type": "string",
            "description": "Plain-English root cause and what the patch does.",
        },
        "confidence": {
            "type": "number",
            "description": "0.0–1.0 confidence that this patch is correct and safe.",
        },
    },
}

EXPLAIN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["reason"],
    "properties": {
        "reason": {
            "type": "string",
            "description": "One plain-English sentence explaining the merge decision.",
        },
    },
}


# ── Validators ─────────────────────────────────────────────────────────────────

def validate_intent(raw: dict[str, Any]) -> bool:
    """
    Validate a raw LLM intent response.
    Returns False (never raises) on any type or value error.
    """
    try:
        assert isinstance(raw.get("before_incident"), bool), "before_incident must be bool"
        assert isinstance(raw.get("remediate"), bool), "remediate must be bool"
        assert isinstance(raw.get("preserve"), list), "preserve must be list"
        confidence = raw.get("confidence")
        assert isinstance(confidence, (int, float)), "confidence must be number"
        assert 0.0 <= float(confidence) <= 1.0, "confidence must be 0–1"
        reasoning = raw.get("reasoning")
        assert isinstance(reasoning, str) and reasoning.strip(), "reasoning must be non-empty str"
        rs = raw.get("rewind_seconds")
        assert rs is None or isinstance(rs, (int, float)), "rewind_seconds must be number or null"
        pc = raw.get("preserve_count")
        assert pc is None or isinstance(pc, (int, float)), "preserve_count must be number or null"
        return True
    except (AssertionError, KeyError, TypeError):
        return False


def validate_patch(raw: dict[str, Any]) -> bool:
    """Validate a raw LLM patch response."""
    try:
        src = raw.get("patched_source")
        assert isinstance(src, str) and len(src) > 50, "patched_source too short or missing"
        expl = raw.get("explanation")
        assert isinstance(expl, str) and expl.strip(), "explanation must be non-empty str"
        confidence = raw.get("confidence")
        assert isinstance(confidence, (int, float)), "confidence must be number"
        assert 0.0 <= float(confidence) <= 1.0, "confidence must be 0–1"
        return True
    except (AssertionError, KeyError, TypeError):
        return False


def validate_explain(raw: dict[str, Any]) -> bool:
    """Validate a raw LLM conflict explanation response."""
    try:
        reason = raw.get("reason")
        assert isinstance(reason, str) and len(reason.strip()) > 5, "reason too short or missing"
        return True
    except (AssertionError, KeyError, TypeError):
        return False

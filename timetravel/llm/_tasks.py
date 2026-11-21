"""
LLM task functions with typed return types.

Each function:
  1. Calls the provider (provider-agnostic — works with Gemini or Bedrock)
  2. Validates the raw response via _schemas.py validators
  3. Returns a typed, frozen dataclass or None on failure
  4. Never raises

The typed dataclasses make it impossible to accidentally access a field that
doesn't exist — shape errors are caught at the task boundary, not deep in
business logic.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from ._schemas import (
    INTENT_SCHEMA, PATCH_SCHEMA, EXPLAIN_SCHEMA,
    validate_intent, validate_patch, validate_explain,
)
from ._prompts import INTENT_SYSTEM, PATCH_SYSTEM, EXPLAIN_TEMPLATE

if TYPE_CHECKING:
    from ._provider import LLMProvider
    from ._config import LLMConfig

logger = logging.getLogger(__name__)


# ── Return types ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class IntentResult:
    """
    Structured result of intent parsing.
    frozen=True: immutable after construction, safe to pass between threads.
    """
    rewind_seconds: float | None
    before_incident: bool
    preserve: tuple[str, ...]       # tuple (not list) for immutability
    preserve_count: int | None
    remediate: bool
    confidence: float
    reasoning: str
    source: str                     # "llm" | "regex"

    def to_dict(self) -> dict[str, Any]:
        """
        Backwards-compatible plain dict for agent.py.
        Callers that only need the original fields get them here.
        confidence and reasoning are included so agent.py can log them.
        """
        return {
            "rewind_seconds": self.rewind_seconds,
            "before_incident": self.before_incident,
            "preserve": list(self.preserve),
            "preserve_count": self.preserve_count,
            "remediate": self.remediate,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "source": self.source,
        }


@dataclass(frozen=True)
class PatchResult:
    """Structured result of an LLM patch proposal."""
    patched_source: str
    explanation: str
    confidence: float
    source: str                     # "llm"


# ── Tasks ──────────────────────────────────────────────────────────────────────

def parse_intent_llm(
    provider: "LLMProvider",
    prompt: str,
    config: "LLMConfig",
) -> IntentResult | None:
    """
    Parse a recovery prompt using the LLM.
    Returns None if provider fails or response fails validation.
    """
    raw = provider.generate_structured(
        prompt=INTENT_SYSTEM.format(prompt=prompt),
        schema=INTENT_SCHEMA,
        timeout_s=config.timeout_s,
    )
    if raw is None:
        return None
    if not validate_intent(raw):
        logger.warning(f"parse_intent_llm: response failed validation — {list(raw.keys())}")
        return None

    return IntentResult(
        rewind_seconds=float(raw["rewind_seconds"]) if raw.get("rewind_seconds") is not None else None,
        before_incident=bool(raw["before_incident"]),
        preserve=tuple(str(x) for x in raw.get("preserve", [])),
        preserve_count=int(raw["preserve_count"]) if raw.get("preserve_count") is not None else None,
        remediate=bool(raw["remediate"]),
        confidence=float(raw["confidence"]),
        reasoning=str(raw["reasoning"]),
        source="llm",
    )


def propose_patch_llm(
    provider: "LLMProvider",
    source: str,
    incident_sql: str,
    rows_affected: int,
    endpoint: str,
    config: "LLMConfig",
) -> PatchResult | None:
    """
    Ask the LLM for a minimal surgical patch to the buggy handler.
    Returns None if provider fails, response fails validation, or confidence is too low.
    """
    raw = provider.generate_structured(
        prompt=PATCH_SYSTEM.format(
            endpoint=endpoint,
            incident_sql=incident_sql,
            rows_affected=rows_affected,
            source=source,
        ),
        schema=PATCH_SCHEMA,
        timeout_s=config.timeout_s,
    )
    if raw is None:
        return None
    if not validate_patch(raw):
        logger.warning(f"propose_patch_llm: response failed validation — {list(raw.keys())}")
        return None
    if float(raw["confidence"]) < 0.5:
        logger.warning(
            f"propose_patch_llm: LLM confidence too low ({raw['confidence']:.0%}) — using regex fallback"
        )
        return None

    return PatchResult(
        patched_source=str(raw["patched_source"]),
        explanation=str(raw["explanation"]),
        confidence=float(raw["confidence"]),
        source="llm",
    )


def explain_conflict_llm(
    provider: "LLMProvider",
    conflict: dict[str, Any],
    config: "LLMConfig",
) -> str | None:
    """
    Generate a plain-English reason for a single merge conflict.
    Returns None if provider fails or response fails validation.
    Designed to be called from a ThreadPoolExecutor — stateless and thread-safe.
    """
    raw = provider.generate_structured(
        prompt=EXPLAIN_TEMPLATE.format(
            kind=conflict.get("kind", "unknown"),
            detail=conflict.get("detail", ""),
            order_id=conflict.get("order_id", "N/A"),
            sku=conflict.get("sku", "N/A"),
            shortfall=conflict.get("shortfall", "N/A"),
        ),
        schema=EXPLAIN_SCHEMA,
        timeout_s=config.timeout_s,
    )
    if raw is None:
        return None
    if not validate_explain(raw):
        logger.warning(f"explain_conflict_llm: response failed validation — {raw}")
        return None
    return str(raw["reason"])

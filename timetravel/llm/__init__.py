"""
Public API for all LLM operations in Time-Travel DB.

Callers (agent.py, tools.py) import ONLY from here.
Internal modules (_provider, _tasks, _schemas, etc.) are private — their
interfaces may change without notice.

Usage:
    from timetravel import llm

    # Always returns a valid result — falls back to regex if LLM unavailable
    result = llm.parse_intent("roll back 2 minutes and fix the bug")
    print(result["source"])   # "llm" or "regex"

    # Returns None if LLM unavailable — caller falls back to regex patcher
    patch = llm.propose_patch(source, sql, rows, endpoint)

    # Enriches conflict dicts in-place with a "reason" field (parallel calls)
    llm.explain_conflicts(conflicts)

    # Check whether LLM is available at all
    if llm.is_available():
        ...
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ._config import LLMConfig
from ._fallback import parse_intent_regex
from ._provider import LLMProvider, make_provider
from ._tasks import (
    IntentResult,
    PatchResult,
    explain_conflict_llm,
    parse_intent_llm,
    propose_patch_llm,
)

logger = logging.getLogger(__name__)

# ── Module-level singleton ─────────────────────────────────────────────────────
# Initialised once at import time. Thread-safe: immutable after construction.

config: LLMConfig = LLMConfig.from_env()
_provider: LLMProvider | None = make_provider(config)

if _provider is None:
    logger.info(
        "LLM running in deterministic-only mode. "
        "Set GEMINI_API_KEY (Gemini) or TT_LLM_PROVIDER=bedrock + AWS credentials to enable AI."
    )


# ── Public API ─────────────────────────────────────────────────────────────────

def is_available() -> bool:
    """True if the LLM provider is configured and successfully initialised."""
    return _provider is not None


def parse_intent(prompt: str) -> dict[str, Any]:
    """
    Parse a recovery prompt into a structured intent dict.

    LLM-first: tries the configured provider, falls back to deterministic regex.
    Always returns a valid dict — never raises, never returns None.

    The dict is backwards-compatible with the old parse_intent() in agent.py.
    Extra keys: "confidence" (float), "reasoning" (str), "source" ("llm"|"regex").
    """
    if _provider is not None:
        result = parse_intent_llm(_provider, prompt, config)
        if result is not None:
            return result.to_dict()
        logger.warning("LLM intent parse failed — using regex fallback")

    return parse_intent_regex(prompt).to_dict()


def propose_patch(
    source: str,
    incident_sql: str,
    rows_affected: int,
    endpoint: str,
) -> PatchResult | None:
    """
    Ask the LLM for a minimal surgical patch to the buggy handler.

    Returns a PatchResult if the LLM succeeds and the response validates.
    Returns None if LLM unavailable or response is unacceptable — the caller
    should fall back to the deterministic regex patcher (_patch_source).
    Never raises.
    """
    if _provider is None:
        return None
    return propose_patch_llm(_provider, source, incident_sql, rows_affected, endpoint, config)


def explain_conflicts(conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Enrich each conflict dict with a plain-English "reason" field in-place.

    - Runs up to 3 LLM calls in parallel (one per conflict).
    - Falls back to conflict["detail"] for any failed individual call.
    - If LLM unavailable or TT_LLM_EXPLAIN=false, sets reason=detail immediately.
    - Never raises. Returns the same list (mutated in-place) for convenience.
    """
    if not conflicts:
        return conflicts

    # Fast path: LLM unavailable or feature disabled
    if _provider is None or not config.explain_conflicts:
        for c in conflicts:
            c.setdefault("reason", c.get("detail", ""))
        return conflicts

    max_workers = min(3, len(conflicts))
    with ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="llm-explain",
    ) as executor:
        future_to_idx = {
            executor.submit(explain_conflict_llm, _provider, conflict, config): i
            for i, conflict in enumerate(conflicts)
        }
        # Give each call timeout_s plus 2s grace for thread overhead
        try:
            for future in as_completed(future_to_idx, timeout=config.timeout_s + 2):
                idx = future_to_idx[future]
                try:
                    reason = future.result()
                    conflicts[idx]["reason"] = reason or conflicts[idx].get("detail", "")
                except Exception as e:
                    logger.warning(f"explain_conflicts: index {idx} failed: {e}")
                    conflicts[idx].setdefault("reason", conflicts[idx].get("detail", ""))
        except Exception:
            # Timeout or executor error — ensure all conflicts have a reason
            for c in conflicts:
                c.setdefault("reason", c.get("detail", ""))

    return conflicts

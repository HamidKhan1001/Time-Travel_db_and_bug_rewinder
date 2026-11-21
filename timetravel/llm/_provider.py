"""
LLMProvider Protocol and concrete implementations (Gemini, Bedrock).

Add a new provider by implementing the LLMProvider Protocol — no other file changes.

Design notes:
- Both providers use native schema enforcement (no manual text parsing):
    Gemini  → response_json_schema (native responseSchema mode)
    Bedrock → Tool Use with forced tool_choice (Claude fills in a typed form)
- Both use a daemon thread + join(timeout) for hard timeouts that work on Windows.
- make_provider() is the only factory — callers never instantiate providers directly.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Protocol, runtime_checkable

from ._config import LLMConfig

logger = logging.getLogger(__name__)


# ── Provider Protocol ──────────────────────────────────────────────────────────

@runtime_checkable
class LLMProvider(Protocol):
    """
    Structural interface every provider must satisfy.
    Callers depend only on this — never on a concrete class.
    """

    def generate_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        timeout_s: int,
    ) -> dict[str, Any] | None:
        """
        Generate a structured JSON response matching `schema`.
        Returns None on any failure — never raises.
        """
        ...


# ── Gemini provider ────────────────────────────────────────────────────────────

class GeminiProvider:
    """
    Gemini API provider using google-genai SDK.
    Uses native responseSchema for guaranteed structured output.
    """

    def __init__(self, config: LLMConfig) -> None:
        from google import genai          # ImportError → caught by make_provider
        self._client = genai.Client(api_key=config.api_key)
        self._model = config.model
        logger.info(f"GeminiProvider ready (model={config.model})")

    def generate_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        timeout_s: int,
    ) -> dict[str, Any] | None:
        import json

        result: dict | None = None
        error: Exception | None = None

        def _call() -> None:
            nonlocal result, error
            try:
                from google.genai import types
                resp = self._client.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_json_schema=schema,
                        temperature=0.1,
                    ),
                )
                result = json.loads(resp.text)
            except Exception as e:
                error = e

        t = threading.Thread(target=_call, daemon=True, name="gemini-call")
        t.start()
        t.join(timeout=timeout_s)

        if t.is_alive():
            logger.warning(f"GeminiProvider: timed out after {timeout_s}s")
            return None
        if error:
            logger.warning(f"GeminiProvider: call failed: {error}")
            return None
        return result


# ── Bedrock provider ───────────────────────────────────────────────────────────

class BedrockProvider:
    """
    AWS Bedrock provider using Claude 3 Haiku with Tool Use.

    Tool Use forces Claude to fill in a typed form matching our schema —
    equivalent to Gemini's native responseSchema. No manual text parsing.

    Credentials are picked up automatically by boto3 from:
      AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY + AWS_DEFAULT_REGION
      or an IAM role attached to the machine.
    """

    def __init__(self, config: LLMConfig) -> None:
        import boto3                      # ImportError → caught by make_provider
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=config.bedrock_region,
        )
        self._model = config.bedrock_model
        logger.info(f"BedrockProvider ready (model={config.bedrock_model}, region={config.bedrock_region})")

    def generate_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        timeout_s: int,
    ) -> dict[str, Any] | None:
        import json

        result: dict | None = None
        error: Exception | None = None

        def _call() -> None:
            nonlocal result, error
            try:
                body = json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 2048,
                    "temperature": 0.1,
                    "tools": [{
                        "name": "structured_output",
                        "description": "Return the structured result for this task.",
                        "input_schema": schema,  # standard JSON Schema (lowercase types)
                    }],
                    # Force Claude to ALWAYS call this tool — no free-text responses
                    "tool_choice": {
                        "type": "tool",
                        "name": "structured_output",
                    },
                    "messages": [{"role": "user", "content": prompt}],
                })
                resp = self._client.invoke_model(
                    modelId=self._model,
                    body=body,
                    contentType="application/json",
                    accept="application/json",
                )
                response_body = json.loads(resp["body"].read())
                # Tool Use response: find the tool_use block → its .input is our structured data
                tool_block = next(
                    (b for b in response_body.get("content", []) if b.get("type") == "tool_use"),
                    None,
                )
                result = tool_block["input"] if tool_block else None
                if result is None:
                    logger.warning("BedrockProvider: no tool_use block in response")
            except Exception as e:
                error = e

        t = threading.Thread(target=_call, daemon=True, name="bedrock-call")
        t.start()
        t.join(timeout=timeout_s)

        if t.is_alive():
            logger.warning(f"BedrockProvider: timed out after {timeout_s}s")
            return None
        if error:
            logger.warning(f"BedrockProvider: call failed: {error}")
            return None
        return result


# ── Factory ────────────────────────────────────────────────────────────────────

_PROVIDER_MAP: dict[str, type] = {
    "gemini":  GeminiProvider,
    "bedrock": BedrockProvider,
}


def make_provider(config: LLMConfig) -> LLMProvider | None:
    """
    Create and return the configured provider.
    Returns None — never raises — if the provider cannot be initialised.
    This is the single entry point for provider construction.
    """
    if not config.is_configured():
        logger.info("LLM: provider not configured — running in deterministic-only mode")
        return None

    cls = _PROVIDER_MAP.get(config.provider)
    if cls is None:
        logger.warning(
            f"LLM: unknown provider '{config.provider}' "
            f"(valid: {list(_PROVIDER_MAP)}). Falling back to regex."
        )
        return None

    try:
        return cls(config)
    except Exception as e:
        logger.warning(f"LLM: '{config.provider}' provider failed to initialise: {e}")
        return None

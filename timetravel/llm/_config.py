"""All LLM configuration in one place. Loaded from environment variables once at import time."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMConfig:
    """
    Immutable configuration snapshot for the LLM layer.
    Frozen so callers cannot accidentally mutate shared state.
    """
    # Gemini
    api_key: str            # GEMINI_API_KEY
    model: str              # TT_LLM_MODEL
    # Bedrock
    bedrock_region: str     # TT_BEDROCK_REGION
    bedrock_model: str      # TT_BEDROCK_MODEL
    # Shared
    provider: str           # TT_LLM_PROVIDER: "gemini" | "bedrock"
    timeout_s: int          # TT_LLM_TIMEOUT
    min_confidence: float   # TT_LLM_MIN_CONFIDENCE
    explain_conflicts: bool # TT_LLM_EXPLAIN

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Create a config from environment variables. Safe to call multiple times."""
        return cls(
            api_key=os.getenv("GEMINI_API_KEY", ""),
            model=os.getenv("TT_LLM_MODEL", "gemini-3.8-flash"),
            bedrock_region=os.getenv("TT_BEDROCK_REGION", "us-east-1"),
            bedrock_model=os.getenv(
                "TT_BEDROCK_MODEL",
                "anthropic.claude-3-haiku-20240307-v1:0",
            ),
            provider=os.getenv("TT_LLM_PROVIDER", "gemini").lower(),
            timeout_s=int(os.getenv("TT_LLM_TIMEOUT", "10")),
            min_confidence=float(os.getenv("TT_LLM_MIN_CONFIDENCE", "0.7")),
            explain_conflicts=os.getenv("TT_LLM_EXPLAIN", "true").lower() == "true",
        )

    def is_configured(self) -> bool:
        """True if the selected provider has the credentials it needs."""
        if self.provider == "gemini":
            return bool(self.api_key)
        if self.provider == "bedrock":
            # boto3 reads AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / IAM role automatically
            return True
        return False

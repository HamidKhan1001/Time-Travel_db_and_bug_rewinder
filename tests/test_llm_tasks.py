"""Unit tests for task functions using a mock provider (stdlib unittest)."""
import unittest
from unittest.mock import MagicMock

from timetravel.llm._config import LLMConfig
from timetravel.llm._tasks import (
    IntentResult,
    PatchResult,
    explain_conflict_llm,
    parse_intent_llm,
    propose_patch_llm,
)


class TestLLMTasks(unittest.TestCase):
    def setUp(self):
        self.cfg = LLMConfig(
            api_key="dummy",
            model="gemini-3.8-flash",
            timeout_s=5,
            min_confidence=0.7,
            explain_conflicts=True,
            provider="gemini",
            bedrock_region="us-east-1",
            bedrock_model="anthropic.claude-3-haiku-20240307-v1:0",
        )
        self.provider = MagicMock()

    def test_parse_intent_success(self):
        self.provider.generate_structured.return_value = {
            "rewind_seconds": 120.0,
            "before_incident": False,
            "preserve": ["orders"],
            "preserve_count": 3,
            "remediate": True,
            "confidence": 0.95,
            "reasoning": "2 min ago",
        }
        result = parse_intent_llm(self.provider, "2 minutes ago", self.cfg)
        self.assertIsInstance(result, IntentResult)
        self.assertEqual(result.rewind_seconds, 120.0)
        self.assertEqual(result.source, "llm")

    def test_parse_intent_provider_returns_none(self):
        self.provider.generate_structured.return_value = None
        self.assertIsNone(parse_intent_llm(self.provider, "anything", self.cfg))

    def test_parse_intent_invalid_response(self):
        self.provider.generate_structured.return_value = {"confidence": 2.0}
        self.assertIsNone(parse_intent_llm(self.provider, "anything", self.cfg))

    def test_propose_patch_success(self):
        self.provider.generate_structured.return_value = {
            "patched_source": "def sync_stock(): pass\n" + ("# code\n" * 10),
            "explanation": "Scoped UPDATE to WHERE sku = ?",
            "confidence": 0.9,
        }
        result = propose_patch_llm(
            self.provider,
            "source code",
            "UPDATE inventory SET stock=?",
            1420,
            "POST /api/admin/sync-stock",
            self.cfg,
        )
        self.assertIsInstance(result, PatchResult)
        self.assertEqual(result.source, "llm")
        self.assertEqual(result.confidence, 0.9)

    def test_propose_patch_low_confidence_rejected(self):
        self.provider.generate_structured.return_value = {
            "patched_source": "def sync_stock(): pass\n" + ("# code\n" * 10),
            "explanation": "Not sure about this patch",
            "confidence": 0.3,
        }
        result = propose_patch_llm(
            self.provider,
            "source code",
            "UPDATE inventory SET stock=?",
            1420,
            "POST /api/admin/sync-stock",
            self.cfg,
        )
        self.assertIsNone(result)

    def test_explain_conflict_success(self):
        self.provider.generate_structured.return_value = {"reason": "Order kept and marked backorder."}
        r = explain_conflict_llm(
            self.provider,
            {"kind": "oversell", "detail": "short", "order_id": 1},
            self.cfg,
        )
        self.assertEqual(r, "Order kept and marked backorder.")

    def test_explain_conflict_bad_response(self):
        self.provider.generate_structured.return_value = {"reason": "bad"}
        self.assertIsNone(explain_conflict_llm(self.provider, {"kind": "oversell", "detail": "d"}, self.cfg))


if __name__ == "__main__":
    unittest.main()

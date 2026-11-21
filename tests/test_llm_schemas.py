"""Unit tests for schema validators (stdlib unittest)."""
import unittest

from timetravel.llm._schemas import validate_explain, validate_intent, validate_patch


class TestLLMSchemas(unittest.TestCase):
    def test_intent_valid(self):
        self.assertTrue(validate_intent({
            "rewind_seconds": 120.0,
            "before_incident": False,
            "preserve": ["orders"],
            "preserve_count": 3,
            "remediate": True,
            "confidence": 0.95,
            "reasoning": "2 min ago",
        }))

    def test_intent_null_rewind(self):
        self.assertTrue(validate_intent({
            "rewind_seconds": None,
            "before_incident": True,
            "preserve": [],
            "preserve_count": None,
            "remediate": False,
            "confidence": 0.8,
            "reasoning": "before crash",
        }))

    def test_intent_bad_confidence(self):
        self.assertFalse(validate_intent({
            "rewind_seconds": 60,
            "before_incident": False,
            "preserve": [],
            "preserve_count": None,
            "remediate": False,
            "confidence": 1.5,  # out of 0..1 range
            "reasoning": "test",
        }))

    def test_intent_missing_field(self):
        self.assertFalse(validate_intent({"rewind_seconds": 60}))

    def test_patch_valid(self):
        self.assertTrue(validate_patch({
            "patched_source": "def sync_stock(): pass\n" + ("# code line\n" * 10),
            "explanation": "Fixed the WHERE clause",
            "confidence": 0.9,
        }))

    def test_patch_empty_source(self):
        self.assertFalse(validate_patch({
            "patched_source": "",  # too short
            "explanation": "Fixed",
            "confidence": 0.9,
        }))

    def test_explain_valid(self):
        self.assertTrue(validate_explain({"reason": "Order kept and flagged as backorder."}))

    def test_explain_too_short(self):
        self.assertFalse(validate_explain({"reason": "ok"}))


if __name__ == "__main__":
    unittest.main()

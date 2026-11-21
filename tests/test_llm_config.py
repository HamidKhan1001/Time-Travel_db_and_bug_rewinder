"""Unit tests for LLMConfig (stdlib unittest)."""
import os
import unittest

from timetravel.llm._config import LLMConfig


class TestLLMConfig(unittest.TestCase):
    def setUp(self):
        self._orig_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)

    def test_defaults(self):
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("TT_LLM_PROVIDER", None)
        cfg = LLMConfig.from_env()
        self.assertEqual(cfg.model, "gemini-3.8-flash")
        self.assertEqual(cfg.timeout_s, 10)
        self.assertEqual(cfg.min_confidence, 0.7)
        self.assertTrue(cfg.explain_conflicts)
        self.assertFalse(cfg.is_configured())

    def test_custom_values(self):
        os.environ["GEMINI_API_KEY"] = "test-key"
        os.environ["TT_LLM_MODEL"] = "gemini-3.5-flash-lite"
        os.environ["TT_LLM_TIMEOUT"] = "5"
        os.environ["TT_LLM_MIN_CONFIDENCE"] = "0.85"
        cfg = LLMConfig.from_env()
        self.assertEqual(cfg.api_key, "test-key")
        self.assertEqual(cfg.model, "gemini-3.5-flash-lite")
        self.assertEqual(cfg.timeout_s, 5)
        self.assertEqual(cfg.min_confidence, 0.85)
        self.assertTrue(cfg.is_configured())

    def test_explain_flag(self):
        os.environ["TT_LLM_EXPLAIN"] = "false"
        cfg = LLMConfig.from_env()
        self.assertFalse(cfg.explain_conflicts)

    def test_bedrock_configured_without_api_key(self):
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ["TT_LLM_PROVIDER"] = "bedrock"
        cfg = LLMConfig.from_env()
        self.assertEqual(cfg.provider, "bedrock")
        self.assertTrue(cfg.is_configured())  # Bedrock relies on AWS env / IAM


if __name__ == "__main__":
    unittest.main()

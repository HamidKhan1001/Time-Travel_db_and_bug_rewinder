"""Unit tests for the regex fallback parser (stdlib unittest)."""
import unittest

from timetravel.llm._fallback import parse_intent_regex


class TestLLMFallback(unittest.TestCase):
    def test_minutes(self):
        r = parse_intent_regex("Take the business back to 2 minutes ago")
        self.assertEqual(r.rewind_seconds, 120.0)
        self.assertEqual(r.source, "regex")

    def test_seconds(self):
        r = parse_intent_regex("rewind 90 seconds")
        self.assertEqual(r.rewind_seconds, 90.0)

    def test_before_crash(self):
        r = parse_intent_regex("restore to before the crash")
        self.assertTrue(r.before_incident)
        self.assertIsNone(r.rewind_seconds)

    def test_remediate(self):
        r = parse_intent_regex("fix the bug and keep the orders")
        self.assertTrue(r.remediate)
        self.assertIn("orders", r.preserve)

    def test_preserve_count(self):
        r = parse_intent_regex("keep the 3 orders")
        self.assertEqual(r.preserve_count, 3)

    def test_no_match_is_safe(self):
        r = parse_intent_regex("hello world")
        self.assertIsNone(r.rewind_seconds)
        self.assertFalse(r.before_incident)
        self.assertFalse(r.remediate)
        self.assertEqual(r.confidence, 0.9)


if __name__ == "__main__":
    unittest.main()

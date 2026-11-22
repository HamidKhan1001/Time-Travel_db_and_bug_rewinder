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

    def test_before_phrasings(self):
        for text in ("revert to immediately prior to the sync", "go back to before the warehouse sync",
                     "restore the state prior to the outage"):
            self.assertTrue(parse_intent_regex(text).before_incident, text)
        self.assertFalse(parse_intent_regex("the sync ran before lunch").before_incident)

    def test_console_default_prompt_is_understood(self):
        # Must match DEFAULT_PROMPT in frontend/src/constants/defaults.js
        r = parse_intent_regex("The warehouse sync wiped inventory while 3 orders came in. Take the business back "
                               "to before the crash, keep the 3 orders, and fix the bug that caused it.")
        self.assertTrue(r.before_incident)
        self.assertTrue(r.remediate)
        self.assertEqual((r.preserve, r.preserve_count), (["orders"], 3))
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

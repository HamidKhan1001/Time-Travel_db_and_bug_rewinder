"""Deterministic guard fuzz/corpus tests: mixed case, comments, Unicode, and semicolon variants."""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timetravel import guard


class GuardFuzzTests(unittest.TestCase):
    def test_mixed_case_destructive_keywords_blocked(self):
        prefixes = ("", "/* lead */ ", "-- lead\n", "   ", "\t")
        keywords = ("DROP", "drop", "DrOp", "TRUNCATE", "TrUnCaTe", "ALTER", "aLtEr")
        count = 0
        for prefix in prefixes:
            for keyword in keywords:
                sql = f"{prefix}{keyword} TABLE inventory"
                count += 1
                with self.subTest(sql=sql):
                    self.assertFalse(guard.analyze(sql)["allowed"])
        self.assertGreaterEqual(count, 28)

    def test_mixed_case_unscoped_update_variants(self):
        variants = (
            "UPDATE inventory SET stock = 0",
            "update inventory set stock=0",
            "  UpDaTe   inventory\nSET stock = 0 ",
            "/* lead */ UPDATE inventory SET stock = 0",
            "-- lead comment\nUPDATE inventory SET stock = 0",
        )
        for sql in variants:
            with self.subTest(sql=sql):
                result = guard.analyze(sql)
                self.assertFalse(result["allowed"])
                self.assertEqual(result["rule"], "unscoped-write")

    def test_fake_where_in_string_or_comment_does_not_make_write_scoped(self):
        variants = (
            "UPDATE inventory SET name = 'WHERE'",
            'UPDATE inventory SET name = "WHERE sku=APX-0007"',
            "UPDATE inventory SET stock = 0 /* WHERE sku='APX-0007' */",
            "UPDATE inventory SET stock = 0 -- WHERE sku='APX-0007'",
        )
        for sql in variants:
            with self.subTest(sql=sql):
                result = guard.analyze(sql)
                self.assertFalse(result["allowed"])

    def test_real_where_variants_remain_scoped(self):
        variants = (
            "UPDATE inventory SET stock=5 WHERE sku='APX-0007'",
            "UPDATE inventory SET stock=5 WHERE (sku='APX-0007')",
            "DELETE FROM inventory /* harmless */ WHERE sku='APX-0007'",
            "DeLeTe FROM inventory wHeRe sku='APX-0007'",
        )
        for sql in variants:
            with self.subTest(sql=sql):
                self.assertTrue(guard.analyze(sql)["allowed"])

    def test_multiple_statements_with_whitespace_and_comments_are_blocked(self):
        variants = (
            "UPDATE inventory SET stock=0; DELETE FROM orders",
            "UPDATE inventory SET stock=0 ; -- trailing comment\nDELETE FROM orders",
            "SELECT 1; DROP TABLE inventory",
            "UPDATE inventory SET stock=0;/* comment */DELETE FROM orders",
        )
        for sql in variants:
            with self.subTest(sql=sql):
                self.assertFalse(guard.analyze(sql)["allowed"])

    def test_safe_trailing_semicolon_is_allowed(self):
        variants = (
            "SELECT * FROM inventory;",
            "UPDATE inventory SET stock=5 WHERE sku='APX-0007';",
            "DELETE FROM orders WHERE id=1041;",
        )
        for sql in variants:
            with self.subTest(sql=sql):
                self.assertTrue(guard.analyze(sql)["allowed"])

    def test_unicode_and_nasty_spacing_corruptions(self):
        variants = (
            "\u2003UPDATE\u2003inventory SET stock = 0",
            "UPDATE\n\tinventory\r\nSET stock = 0",
            "/* café */ UPDATE inventory SET stock = 0",
            "UPDATE inventory SET name='DROP TABLE inventory' WHERE sku='APX-0007'",
        )
        for sql in variants:
            with self.subTest(sql=sql):
                result = guard.analyze(sql)
                if "WHERE sku" in sql:
                    self.assertTrue(result["allowed"])
                else:
                    self.assertFalse(result["allowed"])

    def test_generated_50_nasty_query_variants(self):
        unscoped = []
        for i in range(50):
            if i % 5 == 0:
                unscoped.append(f"UPDATE inventory SET stock={i}")
            elif i % 5 == 1:
                unscoped.append(f"  /* variant {i} */ UPDATE inventory SET stock={i}")
            elif i % 5 == 2:
                unscoped.append(f"DELETE FROM inventory -- variant {i}")
            elif i % 5 == 3:
                unscoped.append(f"UPDATE inventory SET name='WHERE {i}'")
            else:
                unscoped.append(f"UPDATE inventory SET stock={i}; -- only a comment")

        for sql in unscoped:
            with self.subTest(sql=sql):
                self.assertFalse(guard.analyze(sql)["allowed"])


if __name__ == "__main__":
    unittest.main()

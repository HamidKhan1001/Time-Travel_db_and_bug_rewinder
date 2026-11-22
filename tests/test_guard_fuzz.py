"""Deterministic guard fuzz/corpus tests: mixed case, comments, Unicode, and semicolon variants."""
import sys
import os
import random
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

    def test_seeded_random_policy_fuzz(self):
        """Generate reproducible random variants; never execute generated SQL."""
        rng = random.Random(20261122)
        whitespace = (" ", "  ", "\n", "\t", "\r\n", "\u2003")

        def case_variants(word):
            return {
                word.lower(), word.upper(), word.title(),
                "".join(ch.upper() if i % 2 else ch.lower() for i, ch in enumerate(word)),
            }

        generated = []

        for i in range(150):
            ws = rng.choice(whitespace)
            update = rng.choice(tuple(case_variants("UPDATE")))
            set_word = rng.choice(tuple(case_variants("SET")))
            where_word = rng.choice(tuple(case_variants("WHERE")))
            if i % 3 == 0:
                sql = f"{ws}{update}{ws}inventory{ws}{set_word}{ws}stock=0"
                expected = False
            elif i % 3 == 1:
                sql = f"{ws}{update}{ws}inventory{ws}{set_word}{ws}stock=5{ws}{where_word}{ws}sku='APX-0007'"
                expected = True
            else:
                sql = f"{ws}{update}{ws}inventory{ws}{set_word}{ws}name='WHERE DROP TABLE'{ws}{where_word}{ws}sku='APX-0007'"
                expected = True
            generated.append((sql, expected, f"seeded direct UPDATE variant {i}"))

        for i in range(100):
            ws = rng.choice(whitespace)
            delete = rng.choice(tuple(case_variants("DELETE")))
            from_word = rng.choice(tuple(case_variants("FROM")))
            where_word = rng.choice(tuple(case_variants("WHERE")))
            if i % 2:
                sql = f"{ws}{delete}{ws}{from_word}{ws}inventory{ws}{where_word}{ws}sku='APX-0007'"
                expected = True
            else:
                sql = f"{ws}{delete}{ws}{from_word}{ws}inventory"
                expected = False
            generated.append((sql, expected, f"seeded DELETE variant {i}"))

        for i in range(100):
            ws = rng.choice(whitespace)
            cte_update = rng.choice(tuple(case_variants("UPDATE")))
            set_word = rng.choice(tuple(case_variants("SET")))
            where_word = rng.choice(tuple(case_variants("WHERE")))
            if i % 2:
                sql = f"WITH{ws}recent{ws}AS{ws}(SELECT * FROM inventory WHERE stock > 0){ws}{cte_update}{ws}inventory{ws}{set_word}{ws}stock=0"
                expected = False
            else:
                sql = f"WITH{ws}recent{ws}AS{ws}(SELECT * FROM inventory){ws}{cte_update}{ws}inventory{ws}{set_word}{ws}stock=5{ws}{where_word}{ws}sku='APX-0007'"
                expected = True
            generated.append((sql, expected, f"seeded CTE variant {i}"))

        destructive = ("DROP", "TRUNCATE", "ALTER", "ATTACH", "DETACH")
        for i in range(100):
            keyword = rng.choice(tuple(case_variants(rng.choice(destructive))))
            prefix = rng.choice(("", "/* benign */ ", "-- benign\n", "\u2003"))
            sql = f"{prefix}{keyword} TABLE inventory"
            generated.append((sql, False, f"seeded destructive variant {i}"))

        malformed = (
            "SELECT * FROM inventory; UPDATE inventory SET stock=0",
            "UPDATE inventory SET stock=0; DELETE FROM inventory",
            "UPDATE inventory SET stock=(SELECT stock FROM inventory WHERE sku='APX-0007')",
            "UPDATE inventory SET stock=0 WHERE",
            "WITH recent AS (SELECT * FROM inventory",
            "DELETE inventory WHERE sku='APX-0007'",
        )
        for i in range(50):
            sql = rng.choice(malformed)
            generated.append((sql, False, f"seeded malformed/multi-statement variant {i}"))

        for i, (sql, expected, label) in enumerate(generated):
            with self.subTest(seed=20261122, index=i, label=label, sql=sql):
                result = guard.analyze(sql, approved=False)
                self.assertEqual(result["allowed"], expected,
                                 msg=f"seed=20261122 input={sql!r} got={result!r}")


if __name__ == "__main__":
    unittest.main()

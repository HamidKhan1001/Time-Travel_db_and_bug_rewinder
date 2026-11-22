"""Unit tests for the deterministic SQL safety guard."""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timetravel import guard


class GuardTests(unittest.TestCase):
    def test_scoped_update_is_allowed(self):
        result = guard.analyze("UPDATE inventory SET stock = 10 WHERE sku = 'APX-0007'")
        self.assertTrue(result["allowed"])
        self.assertEqual(result["rule"], "scoped")

    def test_scoped_delete_is_allowed(self):
        result = guard.analyze("DELETE FROM orders WHERE id = 1041")
        self.assertTrue(result["allowed"])
        self.assertEqual(result["rule"], "scoped")

    def test_insert_and_select_are_allowed(self):
        for sql in (
            "INSERT INTO inventory(sku, stock) VALUES('APX-0001', 5)",
            "SELECT * FROM inventory WHERE stock > 0",
        ):
            with self.subTest(sql=sql):
                self.assertTrue(guard.analyze(sql)["allowed"])

    def test_unscoped_update_requires_approval(self):
        result = guard.analyze("UPDATE inventory SET stock = 0")
        self.assertFalse(result["allowed"])
        self.assertEqual(result["rule"], "unscoped-write")

    def test_unscoped_delete_requires_approval(self):
        result = guard.analyze("DELETE FROM inventory")
        self.assertFalse(result["allowed"])
        self.assertEqual(result["rule"], "unscoped-write")

    def test_explicit_approval_allows_unscoped_writes(self):
        for sql in ("UPDATE inventory SET stock = 0", "DELETE FROM inventory"):
            with self.subTest(sql=sql):
                result = guard.analyze(sql, approved=True)
                self.assertTrue(result["allowed"])
                self.assertEqual(result["rule"], "unscoped-approved")

    def test_destructive_ddl_is_blocked_case_insensitively(self):
        for sql in (
            "DROP TABLE inventory",
            "truncate table inventory",
            "ALTER TABLE inventory ADD COLUMN bad TEXT",
            "ATTACH DATABASE 'other.db' AS other",
            "detach database other",
        ):
            with self.subTest(sql=sql):
                result = guard.analyze(sql)
                self.assertFalse(result["allowed"])
                self.assertEqual(result["rule"], "destructive-ddl")

    def test_multiple_statements_are_blocked(self):
        result = guard.analyze("UPDATE inventory SET stock=0; UPDATE orders SET status='bad'")
        self.assertFalse(result["allowed"])
        self.assertEqual(result["rule"], "multi-statement")

    def test_empty_statement_is_allowed_as_scoped_placeholder(self):
        result = guard.analyze("   ")
        self.assertTrue(result["allowed"])

    def test_original_sql_is_preserved_in_result(self):
        sql = "  UPDATE inventory SET stock = 0  "
        result = guard.analyze(sql)
        self.assertEqual(result["sql"], sql)

    def test_is_unscoped_is_deterministic(self):
        self.assertTrue(guard.is_unscoped("UPDATE inventory SET stock = 0"))
        self.assertFalse(guard.is_unscoped("UPDATE inventory SET stock = 0 WHERE sku = 'APX-0007'"))

    def test_nested_where_does_not_scope_update(self):
        sql = "UPDATE inventory SET stock=(SELECT stock FROM inventory WHERE sku='APX-0007')"
        result = guard.analyze(sql)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["rule"], "unscoped-write")

    def test_cte_select_is_allowed(self):
        sql = "WITH recent AS (SELECT * FROM orders WHERE id > 1000) SELECT * FROM recent"
        self.assertTrue(guard.analyze(sql)["allowed"])

    def test_cte_unscoped_update_requires_approval(self):
        sql = "WITH recent AS (SELECT * FROM inventory WHERE stock > 0) UPDATE inventory SET stock=0"
        result = guard.analyze(sql)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["rule"], "unscoped-write")

    def test_cte_scoped_update_is_allowed(self):
        sql = "WITH recent AS (SELECT * FROM inventory) UPDATE inventory SET stock=5 WHERE sku='APX-0007'"
        self.assertTrue(guard.analyze(sql)["allowed"])

    def test_cte_unscoped_delete_requires_approval(self):
        sql = "WITH recent AS (SELECT * FROM inventory) DELETE FROM inventory"
        result = guard.analyze(sql)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["rule"], "unscoped-write")

    def test_malformed_update_and_delete_are_blocked(self):
        for sql in (
            "UPDATE inventory SET",
            "DELETE inventory WHERE sku='APX-0007'",
            "WITH recent AS (SELECT * FROM inventory UPDATE",
            "UPDATE inventory SET stock=0 WHERE",
        ):
            with self.subTest(sql=sql):
                result = guard.analyze(sql)
                self.assertFalse(result["allowed"])

    def test_unicode_identifier_and_whitespace_do_not_bypass(self):
        for sql in (
            "\u2003UPDATE\u2003inventory SET stock=0",
            "UPDATE inventory SET name='Δ'",
            "DELETE\u00a0FROM inventory",
        ):
            with self.subTest(sql=sql):
                result = guard.analyze(sql)
                self.assertFalse(result["allowed"])

    def test_quoted_destructive_word_is_not_treated_as_ddl(self):
        sql = "UPDATE inventory SET name='DROP TABLE inventory' WHERE sku='APX-0007'"
        self.assertTrue(guard.analyze(sql)["allowed"])


if __name__ == "__main__":
    unittest.main()

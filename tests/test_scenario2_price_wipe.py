"""
End-to-end integration test for Scenario 2: Pricing Feed Crash (Price Wipe).
Tests crash -> delta orders -> agent rewind & patch -> HITL approval -> cutover verification -> re-run -> undo.
"""
import os
import sys

os.environ["TT_PACE"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timetravel import agent, appcode, db, seed


def test_scenario2():
    seed.reset()
    c = db.connect()
    try:
        # 1. Healthy baseline
        initial_zero_prices = c.execute("SELECT COUNT(*) FROM inventory WHERE price_cents <= 0").fetchone()[0]
        assert initial_zero_prices == 0, f"Expected 0 zero-price SKUs, got {initial_zero_prices}"

        orig_price = c.execute("SELECT price_cents FROM inventory WHERE sku = 'APX-0042'").fetchone()[0]
        assert orig_price > 0, "Expected positive original price"

        # 2. Trigger pricing crash (unscoped UPDATE zeroes all prices)
        r = appcode.fn("sync_price")(c, {"sku": "APX-0042", "price_cents": 0})
        assert r["updated_rows"] == 1420, f"Expected 1420 rows wiped, got {r['updated_rows']}"
        zero_prices = c.execute("SELECT COUNT(*) FROM inventory WHERE price_cents = 0").fetchone()[0]
        assert zero_prices == 1420, f"Expected 1420 zero-price SKUs, got {zero_prices}"

        # 3. Two orders arrive during outage
        new_orders = seed.demo_orders2()
        assert len(new_orders) == 2, f"Expected 2 orders, got {len(new_orders)}"
    finally:
        c.close()

    # 4. Agent runs time-travel recovery
    s = agent.start(
        "Take the business back to 2 minutes ago, keep the 2 orders that came in after the crash, and fix the bug that caused it.",
        background=False,
    )
    assert s.phase == "awaiting_approval", (s.phase, s.events[-1])
    assert s.patch is not None, "Expected code patch proposal"
    assert s.patch["patch_ok"], "Expected patch to pass sandbox verification"
    assert "price" in s.patch["diff"], "Expected patch diff to modify price handler"
    assert "WHERE sku = ?" in s.patch["diff"], "Expected patch to add WHERE clause"
    print("Scenario 2 patch diff:")
    print(s.patch["diff"])

    # 5. Human approves recovery
    agent.approve(s.id)
    assert s.phase == "applied", f"Expected applied phase, got {s.phase}"

    c = db.connect()
    try:
        # 6. Verify database state after recovery
        zero_prices_after = c.execute("SELECT COUNT(*) FROM inventory WHERE price_cents <= 0").fetchone()[0]
        assert zero_prices_after == 0, f"Expected 0 zero-price SKUs after recovery, got {zero_prices_after}"

        restored_price = c.execute("SELECT price_cents FROM inventory WHERE sku = 'APX-0042'").fetchone()[0]
        assert restored_price == orig_price, f"Expected {orig_price}, got {restored_price}"

        # 7. Post-crash orders preserved
        order_rows = c.execute("SELECT id FROM orders WHERE id > 1040").fetchall()
        assert len(order_rows) == 2, f"Expected 2 preserved orders, got {len(order_rows)}"

        # 8. Re-run the crash action: now safely touches exactly 1 row!
        r_after = appcode.fn("sync_price")(c, {"sku": "APX-0042", "price_cents": 19500})
        assert r_after["updated_rows"] == 1, f"Expected 1 row updated, got {r_after['updated_rows']}"

        # Other SKUs unaffected
        other_zero = c.execute("SELECT COUNT(*) FROM inventory WHERE price_cents <= 0").fetchone()[0]
        assert other_zero == 0, f"Expected 0 zero-price SKUs, got {other_zero}"

        # Missing sku is rejected by guard
        try:
            appcode.fn("sync_price")(c, {"price_cents": 999})
            rejected = False
        except ValueError:
            rejected = True
        assert rejected, "Expected ValueError when sku parameter is omitted"
    finally:
        c.close()

    # 9. Verify undo
    agent.undo(s.id)
    assert s.phase == "undone", f"Expected undone phase, got {s.phase}"

    # 10. Clean reset
    seed.reset()
    print("SCENARIO 2 (PRICE WIPE) PASS")


if __name__ == "__main__":
    test_scenario2()

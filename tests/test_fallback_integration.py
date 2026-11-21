"""
Integration test: LLM unavailable → app still works end-to-end.
Runs the full e2e pipeline with GEMINI_API_KEY explicitly unset.
"""
import os
import sys

os.environ["TT_PACE"] = "0"
os.environ.pop("GEMINI_API_KEY", None)   # force fallback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from timetravel import agent, appcode, db, llm, seed


def test_llm_unavailable_means_fallback():
    assert not llm.is_available()


def test_full_pipeline_without_llm():
    seed.reset()
    c = db.connect()
    try:
        appcode.fn("sync_stock")(c, {"sku": "APX-0007", "stock": 0})
    finally:
        c.close()
    seed.demo_orders()
    s = agent.start(
        "Take the business back to 2 minutes ago, keep the 3 orders, and fix the bug.",
        background=False,
    )
    assert s.phase == "awaiting_approval", s.events[-1]
    assert s.parsed["source"] == "regex"  # confirmed deterministic fallback
    assert s.plan["orders_preserved"] >= 3
    assert len(s.plan["conflicts"]) >= 1
    # Check that conflicts have reasons populated
    for conf in s.plan["conflicts"]:
        assert "reason" in conf and conf["reason"]
    agent.approve(s.id)
    assert s.phase == "applied"
    seed.reset()
    print("Fallback integration test PASS")


if __name__ == "__main__":
    test_llm_unavailable_means_fallback()
    test_full_pipeline_without_llm()

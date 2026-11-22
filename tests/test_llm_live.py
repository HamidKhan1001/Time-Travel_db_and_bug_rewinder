"""
Live LLM smoke-test — Time-Travel DB & Bug Rewinder
====================================================
Runs a real API call against the configured provider so you can verify the
LLM path end-to-end before the hackathon demo.

Usage
-----
    # Gemini (default):
    $env:GEMINI_API_KEY = "your-key"
    python tests/test_llm_live.py

    # Bedrock:
    $env:TT_LLM_PROVIDER = "bedrock"
    $env:AWS_ACCESS_KEY_ID = "..."
    $env:AWS_SECRET_ACCESS_KEY = "..."
    $env:AWS_DEFAULT_REGION = "us-east-1"
    python tests/test_llm_live.py

    # Explicit model override:
    $env:TT_LLM_MODEL = "gemini-3.6-flash"   # or any supported model
    python tests/test_llm_live.py

What it tests
-------------
1. Provider initialises without error (SDK importable, key accepted).
2. parse_intent() returns source="llm" (not "regex") — proves real API call.
3. The returned intent has expected fields with sane values.
4. propose_patch() produces a patched source that contains a WHERE clause.
5. explain_conflicts() enriches a fake conflict with a non-empty reason.

All five tests must pass for the LLM path to be considered proven.
"""
from __future__ import annotations

import os
import sys
import textwrap
import time

# ---------------------------------------------------------------------------
# Make sure the repo root is on sys.path so this script works from any cwd
# ---------------------------------------------------------------------------
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

# ---------------------------------------------------------------------------
# Import the LLM module AFTER sys.path is set
# ---------------------------------------------------------------------------
from timetravel import llm  # noqa: E402  (import after path setup)

PASS = "✅ PASS"
FAIL = "❌ FAIL"
SKIP = "⏭  SKIP"

_buggy_source = textwrap.dedent("""\
    \"\"\"Application request handlers for Apex Gear Storefront.\"\"\"
    import sqlite3, time, json

    DB = "data/live.db"

    def sync_stock(sku_id: int, new_stock: int) -> dict:
        \"\"\"Warehouse sync: set stock level for a single SKU.\"\"\"
        con = sqlite3.connect(DB)
        try:
            # BUG: missing WHERE clause — wipes ALL rows
            con.execute("UPDATE inventory SET stock = ?", (new_stock,))
            con.commit()
            return {"ok": True, "affected": con.total_changes}
        finally:
            con.close()
""")


def _header(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def test_provider_configured() -> bool:
    _header("Test 1 — Provider configured & initialised")
    cfg = llm.config
    print(f"  Provider : {cfg.provider}")
    print(f"  Model    : {cfg.model if cfg.provider == 'gemini' else cfg.bedrock_model}")
    print(f"  Timeout  : {cfg.timeout_s}s")
    available = llm.is_available()
    print(f"  LLM available: {available}")
    if not available:
        if cfg.provider == "gemini" and not cfg.api_key:
            print(f"  {FAIL} — GEMINI_API_KEY is not set.")
        elif cfg.provider == "bedrock":
            print(f"  {FAIL} — Bedrock credentials missing or boto3 not installed.")
        else:
            print(f"  {FAIL} — Provider '{cfg.provider}' could not be initialised.")
        return False
    print(f"  {PASS}")
    return True


def test_parse_intent() -> bool:
    _header("Test 2 — parse_intent() hits the real LLM")
    prompt = "Roll back 2 minutes before the crash, keep the 3 orders, and fix the bug."
    t0 = time.monotonic()
    result = llm.parse_intent(prompt)
    elapsed = time.monotonic() - t0

    print(f"  Prompt   : {prompt}")
    print(f"  Source   : {result.get('source')}")
    print(f"  Confidence: {result.get('confidence')}")
    print(f"  Reasoning: {result.get('reasoning')}")
    print(f"  Rewind   : {result.get('rewind_seconds')}s")
    print(f"  Before incident: {result.get('before_incident')}")
    print(f"  Preserve : {result.get('preserve')}")
    print(f"  Remediate: {result.get('remediate')}")
    print(f"  Elapsed  : {elapsed:.2f}s")

    if result.get("source") != "llm":
        print(f"  {FAIL} — Got source='{result.get('source')}', expected 'llm'. "
              "LLM provider may have failed and fallen back to regex.")
        return False

    # Sanity checks on values
    failures = []
    if result.get("rewind_seconds") is None or abs(result["rewind_seconds"] - 120) > 10:
        failures.append(f"rewind_seconds={result.get('rewind_seconds')} (expected ~120)")
    if not result.get("before_incident"):
        failures.append("before_incident=False (expected True)")
    if "orders" not in result.get("preserve", []):
        failures.append(f"preserve={result.get('preserve')} (expected to contain 'orders')")
    if not result.get("remediate"):
        failures.append("remediate=False (expected True)")

    if failures:
        print(f"  {FAIL} — Value mismatches:")
        for f in failures:
            print(f"    • {f}")
        return False

    print(f"  {PASS}")
    return True


def test_propose_patch() -> bool:
    _header("Test 3 — propose_patch() produces a valid LLM patch")
    if not llm.is_available():
        print(f"  {SKIP} — LLM not configured, skipping patch test.")
        return True  # Don't fail the suite for this

    t0 = time.monotonic()
    patch = llm.propose_patch(
        source=_buggy_source,
        incident_sql="UPDATE inventory SET stock = ?",
        rows_affected=1420,
        endpoint="/sync_stock",
    )
    elapsed = time.monotonic() - t0

    if patch is None:
        print(f"  {FAIL} — propose_patch() returned None (LLM failed or confidence too low).")
        return False

    print(f"  Source   : {patch.source}")
    print(f"  Confidence: {patch.confidence:.0%}")
    print(f"  Explanation: {patch.explanation[:120]}...")
    print(f"  Elapsed  : {elapsed:.2f}s")

    if "WHERE" not in patch.patched_source.upper():
        print(f"  {FAIL} — Patched source contains no WHERE clause!")
        return False

    if patch.confidence < 0.5:
        print(f"  {FAIL} — Confidence {patch.confidence:.0%} is below 50% threshold.")
        return False

    print(f"  {PASS}")
    return True


def test_explain_conflicts() -> bool:
    _header("Test 4 — explain_conflicts() enriches conflicts via LLM")
    if not llm.is_available() or not llm.config.explain_conflicts:
        print(f"  {SKIP} — LLM not configured or TT_LLM_EXPLAIN=false.")
        return True

    fake_conflicts = [
        {
            "kind": "oversell",
            "detail": "Order #1043 requests 5 units of APX-0777 but only 2 are available.",
            "order_id": "1043",
            "sku": "APX-0777",
            "shortfall": 3,
        }
    ]

    t0 = time.monotonic()
    enriched = llm.explain_conflicts(fake_conflicts)
    elapsed = time.monotonic() - t0

    reason = enriched[0].get("reason", "")
    print(f"  Reason   : {reason}")
    print(f"  Elapsed  : {elapsed:.2f}s")

    if not reason or reason == fake_conflicts[0]["detail"]:
        print(f"  {FAIL} — reason is empty or identical to raw detail (LLM may not have fired).")
        return False

    print(f"  {PASS}")
    return True


def main() -> None:
    print("\n" + "=" * 60)
    print("  Time-Travel DB — Live LLM Smoke-Test")
    print(f"  Provider : {llm.config.provider}")
    model_name = llm.config.model if llm.config.provider == "gemini" else llm.config.bedrock_model
    print(f"  Model    : {model_name}")
    print("=" * 60)

    results = {}
    results["Provider configured"] = test_provider_configured()
    if llm.is_available():
        time.sleep(1.5)
        results["parse_intent (LLM)"] = test_parse_intent()
        time.sleep(1.5)
        results["propose_patch (LLM)"] = test_propose_patch()
        time.sleep(1.5)
        results["explain_conflicts (LLM)"] = test_explain_conflicts()
    else:
        results["parse_intent (LLM)"] = None
        results["propose_patch (LLM)"] = None
        results["explain_conflicts (LLM)"] = None

    _header("Summary")
    total = passed = skipped = failed = 0
    for name, result in results.items():
        total += 1
        if result is None:
            icon = SKIP
            skipped += 1
        elif result:
            icon = PASS
            passed += 1
        else:
            icon = FAIL
            failed += 1
        print(f"  {icon}  {name}")

    print(f"\n  {passed}/{total} passed, {skipped} skipped, {failed} failed")

    if failed > 0:
        print("\n  LLM path NOT proven. See failures above.\n")
        sys.exit(1)
    elif not llm.is_available():
        print("\n  LLM path NOT tested (no key). Set GEMINI_API_KEY and re-run.\n")
        sys.exit(2)
    else:
        print("\n  LLM path PROVEN ✅ — safe to demo with live AI.\n")
        sys.exit(0)


if __name__ == "__main__":
    main()

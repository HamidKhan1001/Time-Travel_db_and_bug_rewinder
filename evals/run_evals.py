"""Evaluate the intent parsers against hand-labelled prompts.

    python3 evals/run_evals.py                  # rule-based fallback only (no keys needed)
    TT_LLM_PROVIDER=gemini GEMINI_API_KEY=... python3 evals/run_evals.py --llm

Expected values are written from the user's intent, not from what any parser returns, so the
rule-based score shows honestly where it falls short and where an LLM has to earn its keep.
A case passes only if every field matches. Exit code is 1 if the rule-based score drops below the
recorded baseline (evals/baseline.json), so regressions fail CI.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from timetravel.llm._fallback import parse_intent_regex  # noqa: E402

FIELDS = ("rewind_seconds", "before_incident", "preserve", "preserve_count", "remediate")


def load_cases():
    with open(os.path.join(HERE, "intent_cases.json"), encoding="utf-8") as handle:
        return json.load(handle)


def regex_parser(prompt):
    result = parse_intent_regex(prompt)
    return {field: getattr(result, field) for field in FIELDS}


def llm_parser(prompt):
    from timetravel import llm
    parsed = llm.parse_intent(prompt)
    return {field: parsed.get(field) for field in FIELDS}


def field_ok(field, got, want):
    if field == "rewind_seconds":
        return (got is None and want is None) or (got is not None and want is not None and abs(got - want) < 1)
    if field == "preserve":
        return sorted(got or []) == sorted(want)
    return got == want


def evaluate(parser, cases):
    per_field = dict.fromkeys(FIELDS, 0)
    by_tag = {}
    failures = []
    passed = 0
    for case in cases:
        got = parser(case["prompt"])
        wrong = [f for f in FIELDS if not field_ok(f, got.get(f), case["expected"][f])]
        for field in FIELDS:
            per_field[field] += field not in wrong
        ok = not wrong
        passed += ok
        tag = by_tag.setdefault(case["tag"], [0, 0])
        tag[0] += ok
        tag[1] += 1
        if not ok:
            failures.append({"id": case["id"], "prompt": case["prompt"], "wrong_fields": wrong})
    return {"passed": passed, "total": len(cases), "per_field": per_field,
            "by_tag": {k: {"passed": v[0], "total": v[1]} for k, v in by_tag.items()}, "failures": failures}


def print_report(name, report):
    total = report["total"]
    print(f"\n{name}: {report['passed']}/{total} prompts fully correct ({report['passed'] / total:.0%})")
    for tag, value in sorted(report["by_tag"].items()):
        print(f"  {tag:<11} {value['passed']}/{value['total']}")
    print("  per field: " + ", ".join(f"{f} {n}/{total}" for f, n in report["per_field"].items()))
    for failure in report["failures"]:
        print(f"  MISS {failure['id']} {failure['wrong_fields']}: {failure['prompt']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true", help="also evaluate the configured LLM provider (needs credentials)")
    parser.add_argument("--output", help="write the JSON report here")
    args = parser.parse_args()

    cases = load_cases()
    report = {"rule_based": evaluate(regex_parser, cases)}
    print_report("Rule-based fallback", report["rule_based"])

    if args.llm:
        from timetravel import llm
        if not llm.config.is_configured():
            print("\nLLM not configured (set TT_LLM_PROVIDER and credentials); skipping.")
        else:
            report["llm"] = evaluate(llm_parser, cases)
            print_report(f"LLM ({llm.config.provider})", report["llm"])

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)

    with open(os.path.join(HERE, "baseline.json"), encoding="utf-8") as handle:
        baseline = json.load(handle)["rule_based_passed"]
    if report["rule_based"]["passed"] < baseline:
        print(f"\nREGRESSION: rule-based passed {report['rule_based']['passed']}, baseline is {baseline}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

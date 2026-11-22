# 0003. The LLM proposes; deterministic code verifies

**Status:** accepted.

## Context
Language models are good at reading a vague request ("half an hour ago, keep the orders") and a buggy handler, and bad at being trusted. A wrong patch or a misread rewind point must not reach production, and the demo must still work with no API key.

## Decision
The LLM layer (`timetravel/llm/`) has three jobs: parse the request into a structured intent, propose a code patch, and explain merge decisions in plain English. Its output is validated against a schema and a confidence threshold; invalid output, an error, a timeout or a low-confidence patch falls back to a deterministic rule-based implementation. The model cannot execute anything. Its proposals are then checked by code: the patch must pass tests on a clone, the SQL guard classifies the offending statement, and a human approves.

## Consequences
- The system degrades gracefully: without credentials it uses the regex parser and pattern patcher, and the demo and the test suite do not need a key.
- The rule-based parser is weak on paraphrases (16 of 24 hand-labelled prompts; see `evals/`). Closing that gap is the LLM's job and is measured by `evals/run_evals.py --llm`.
- Gap: the live-LLM path has so far been tested with mocks only; no score against a real model is recorded yet.
- Provider choice (Gemini, Bedrock) is configuration, not architecture.

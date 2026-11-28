# Contributing

## Set up

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # ruff, mypy, coverage, pip-audit (the core needs nothing)
cd frontend && npm install && cd ..
```

Run the app with `python3 server.py` (build the UI first: `cd frontend && npm run build:live`). Use `npm run dev:live` inside `frontend/` for hot reload against the real server.

## Before you open a PR

CI runs exactly these, so run them locally first:

```bash
ruff check .
mypy
coverage run tests/run_ci_suite.py && coverage report     # fails under 75%
python3 evals/run_evals.py
(cd frontend && npm run lint && npm test && npm run test:e2e)
```

`npm run test:e2e` starts its own server on port 8123 with a fresh seed. If you do not want to download Playwright's Chromium, use your installed Chrome: `PW_CHANNEL=chrome npm run test:e2e`.

Rules of thumb:

- **Tests for behaviour changes.** A bug fix gets a regression test that fails without the fix.
- **API changes** update `docs/openapi.json` and `API.md`. A contract test compares `docs/openapi.json` with the router in `timetravel/web/routes/` and fails if they disagree. A new endpoint is a function in `routes/` plus one `router.get/post` line.
- **Never "fix" `app/handlers.py` or `seed/handlers_buggy.py.txt`.** The bug in the storefront handler *is* the demo, and ruff excludes those paths on purpose.
- **Do not run `tests/e2e.py` from the repo root** if you want to keep your `data/` and `app/handlers.py`; use `python3 tests/e2e_isolated.py`.
- Keep the core (`timetravel/`, `server.py`) free of third-party imports. See [ADR 0006](docs/adr/0006-standard-library-core.md).
- Decisions that change the design get an ADR in `docs/adr/`.

## Pull requests

1. Branch from `main`, keep the PR focused, fill in the template.
2. CI runs lint, type check, tests on Python 3.11 and 3.12, evals, the frontend build and e2e, dependency audits and a Docker build. A final **Quality gate** job passes only if all of them did.
3. When the gate passes, **hamid_bot** approves the PR automatically if it is low-risk. It will not approve, and a human must review, when the PR:
   - touches `.github/` (workflows, CODEOWNERS), `timetravel/guard.py`, `pyproject.toml`, `requirements*.txt` or `frontend/package*.json`;
   - comes from a fork, or is a draft.
4. Merging is manual. `CODEOWNERS` lists paths that always need a person.

### hamid_bot setup (maintainers)

The bot is the reusable workflow [`.github/workflows/hamid_bot.yml`](.github/workflows/hamid_bot.yml), called from CI after the quality gate.

- Enable **Settings → Actions → General → "Allow GitHub Actions to create and approve pull requests"**.
- In branch protection for `main`: require the **Quality gate** check, dismiss stale approvals on new commits, and require review from Code Owners.
- By default approvals come from `github-actions[bot]`. To make them come from a dedicated `hamid_bot` account, create that account, give it write access, and store its personal access token (scope `repo`) as the repository secret `HAMID_BOT_TOKEN`. The workflow uses it automatically when present.

A bot approval counts as a review, so with the branch protection above the only human gate left on low-risk PRs is the merge button. Keep the protected-path list in `hamid_bot.yml` honest.

## Reporting security problems

See [SECURITY.md](SECURITY.md). Do not open a public issue for a vulnerability.

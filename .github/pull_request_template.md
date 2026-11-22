## What and why

## How it was tested
- [ ] `python3 tests/run_ci_suite.py`
- [ ] `cd frontend && npm test`
- [ ] Ran the demo flow (reset, crash, orders, time-travel, approve, re-run, undo)

## Risk
- [ ] Touches the SQL guard, apply/undo, or the audit log (needs a human reviewer)
- [ ] Changes an API response shape (update `API.md` and `frontend/src/services/adapters.js`)

---
name: running-unit-tests
description: Runs the QuAIA unit test suite with uv and pytest, diagnoses failing tests and fixes their root cause. Use when the user asks to run the tests, when tests fail, or to verify a change before reporting it as done.
---

# Running Unit Tests

## Commands

The suite, single files and coverage are in *Commands* of `AGENTS.md`. For diagnosis also:

```bash
uv run pytest "tests/orchestrator/test_endpoints.py::test_name" -v --tb=long   # one test with the full traceback
uv run pytest --lf -x                                                          # last failures only, stop at the first
```

## Fix loop

Copy this checklist and track progress:

```
- [ ] Run the full suite and list the failing tests
- [ ] Reproduce one failure in isolation
- [ ] Find the root cause and decide: code bug or outdated test
- [ ] Fix it and re-run that test
- [ ] Repeat for the remaining failures
- [ ] Re-run the full suite
```

1. **Reproduce** each failure alone with `-v --tb=long`.
2. **Decide what is wrong.** Check recent changes to the code under test (`git diff`, `git log -p -- <file>`). If an intentional change altered the behaviour, update the test; otherwise fix the code. If the intended behaviour is unclear, ask the user instead of making the test match the code.
3. **Fix the root cause**, following `PYTHON_GUIDELINES.md` (§ 13 for test code). The project-specific failure causes and their fixes are in *Unit tests* of `AGENTS.md`.
4. **Verify** the single test, then the full suite, so the fix introduces no regression.

## Done when

- `uv run pytest` passes without new warnings.
- Each fix is minimal, and the summary to the user states per failure whether the code or the test was wrong.

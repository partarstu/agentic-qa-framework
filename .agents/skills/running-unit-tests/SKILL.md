---
name: running-unit-tests
description: Runs the QuAIA unit test suite with uv and pytest, diagnoses failing tests and fixes their root cause. Use when the user asks to run the tests, when tests fail, or to verify a change before reporting it as done.
---

# Running Unit Tests

## Commands

Run from the repository root:

```bash
uv run pytest                                            # full unit suite
uv run pytest tests/orchestrator/test_endpoints.py -v    # one file
uv run pytest "tests/orchestrator/test_endpoints.py::test_name" -v --tb=long
uv run pytest --lf -x                                    # last failures only, stop at the first
uv run pytest --cov=. --cov-report=term-missing          # coverage, as CI runs it
```

If imports fail on third-party packages, run `uv sync` first.

`pytest.ini` excludes the `smoke` marker. Do not run `-m smoke` from this skill: the smoke suite needs the
`docker-compose.smoke.yml` stack and makes billed LLM calls (see *Hermetic smoke suite* in `AGENTS.md`).

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
2. **Decide what is wrong.** Check recent changes to the code under test (`git diff`, `git log -p -- <file>`). If an
   intentional change altered the behaviour, update the test; otherwise fix the code. If the intended behaviour is
   unclear, ask the user instead of making the test match the code.
3. **Fix the root cause**, following `PYTHON_GUIDELINES.md` (§ 13 for test code).
4. **Verify** the single test, then the full suite, so the fix introduces no regression.

## Project-specific failure causes

| Symptom                                                                 | Likely cause and fix                                                                                                                         |
|-------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------|
| `RuntimeError: no running event loop` in a sync test                    | Code under test called `_handle_exception` or `_record_error`, which schedule `error_history.add` as a task. Make the test `async def` and patch `orchestrator.main.error_history` (see `mock_error_history` in `tests/orchestrator/test_parsing_logic.py`). |
| `401`/`503` from an orchestrator endpoint test                          | Auth not overridden. Use `orchestrator_app.dependency_overrides[_validate_api_key]`; patching `_validate_api_key` has no effect on `Depends`. |
| `TypeError`/`AttributeError` on a2a types (`root`, `artifactId`, `mimeType`) | The test uses the old a2a-sdk 0.x API. Use the current one: `Part(text=...)`, `Part(raw=..., media_type=...)`, snake_case fields.       |
| Passes alone, fails in the full run                                     | Leaked module state: agent registry, `dependency_overrides`, or `sys.modules` stubs. Reset it in a fixture.                                  |
| Slow test or real network call                                          | A boundary is not mocked (LLM, MCP, Jira, Qdrant, `httpx`). Mock it as `PYTHON_GUIDELINES.md` § 13 describes.                                |
| Missing environment variable or settings error at import               | `tests/conftest.py` provides test env vars; add newly required ones there.                                                                   |

## Done when

- `uv run pytest` passes without new warnings.
- Each fix is minimal, and the summary to the user states per failure whether the code or the test was wrong.

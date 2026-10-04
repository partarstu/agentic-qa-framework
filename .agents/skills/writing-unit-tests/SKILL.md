---
name: writing-unit-tests
description: Writes pytest unit tests for QuAIA agents, orchestrator endpoints and logic, and common utilities, following the project's existing test patterns and mocking conventions. Use when adding or updating tests for new or changed code.
---

# Writing Unit Tests

Tests follow `PYTHON_GUIDELINES.md` § 13 and *Unit tests* in `AGENTS.md`. This skill adds the setup and conventions for writing new tests.

## Setup facts

- `pytest.ini` sets `pythonpath = .`, `testpaths = tests` and `asyncio_mode = auto` (async tests need no marker; match the style of the file you edit).
- Tests mirror the source tree: `tests/agents/`, `tests/orchestrator/` (shared stubs in its `conftest.py`), `tests/common/`, `tests/scripts/`. `tests/smoke/` is the separate end-to-end suite.
- New test files are named `test_<module>.py`.

## Follow the existing tests

Read the closest existing test before writing a new one, and reuse its fixtures and helpers instead of copying them:

| Testing                                   | Model on                                        |
|-------------------------------------------|-------------------------------------------------|
| Agent construction and configuration      | `tests/agents/test_requirements_review.py`      |
| Agent custom tools and sub-agents         | `tests/agents/test_test_case_review.py`         |
| Orchestrator endpoints                    | `tests/orchestrator/test_endpoints.py`          |
| Artifact parsing helpers                  | `tests/orchestrator/test_parsing_logic.py`      |
| Agent discovery, selection and registry   | `tests/orchestrator/test_orchestrator_logic.py` |
| `AgentBase` and the A2A server            | `tests/common/test_agent_base.py`               |

## Project conventions

1. **a2a-sdk 1.x types** in test data: `Artifact(name=..., parts=[Part(text=...)])`, `Part(raw=b"...", media_type="text/plain", filename=...)`, `TaskStatus(state=TaskState.TASK_STATE_COMPLETED)`, `AgentCard(..., supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url=...)])`.
2. **Patch targets** are the modules that use a name: `agents.<agent_name>.main.config`, `orchestrator.main._send_task_to_agent`.
3. **Configuration**: override values with `monkeypatch.setattr(config.<Name>Config, "FIELD", value)` or by patching the module's `config`; never assign to config globals directly.
4. **Module-global state** is reset by a fixture such as `clear_registry` in `tests/orchestrator/test_orchestrator_logic.py`.

## What to cover

Cover what `PYTHON_GUIDELINES.md` § 13 requires. The failure paths this project's code handles explicitly are usually a raised `HTTPException` status, a returned `AgentExecutionError` and logged-and-continued errors.

## Verify

```bash
uv run pytest tests/<path>/test_<module>.py -v
uv run ruff check tests/<path>/test_<module>.py
uv run pytest
```

All three must pass. If anything fails, continue with the `running-unit-tests` skill.

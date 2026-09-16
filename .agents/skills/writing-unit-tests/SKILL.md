---
name: writing-unit-tests
description: Writes pytest unit tests for QuAIA agents, orchestrator endpoints and logic, and common utilities, following the project's existing test patterns and mocking conventions. Use when adding or updating tests for new or changed code.
---

# Writing Unit Tests

Tests follow `PYTHON_GUIDELINES.md`, in particular § 13 Testing. This skill adds the project's setup and conventions.

## Setup facts

- `pytest.ini` sets `pythonpath = .`, `testpaths = tests`, `asyncio_mode = auto` (async tests need no marker; match
  the style of the file you edit) and deselects the `smoke` marker.
- `tests/conftest.py` sets dummy API keys and auth env vars, disables prompt-injection checks and stubs
  `sentence_transformers` in `sys.modules`. Put new collection-time requirements there.
- Tests mirror the source tree: `tests/agents/`, `tests/orchestrator/` (shared stubs in its `conftest.py`),
  `tests/common/`, `tests/scripts/`. `tests/smoke/` is the separate end-to-end suite.
- New test files are named `test_<module>.py` and start with the SPDX header used by every other file.

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

## Project conventions and pitfalls

1. **a2a-sdk types** follow the current 1.x API with snake_case fields:
   `Artifact(name=..., parts=[Part(text=...)])`, `Part(raw=b"...", media_type="text/plain", filename=...)`,
   `TaskStatus(state=TaskState.TASK_STATE_COMPLETED)`,
   `AgentCard(..., supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url=...)])`.
2. **Endpoint auth**: override the dependency with `orchestrator_app.dependency_overrides[_validate_api_key]`.
   Patching `orchestrator.main._validate_api_key` does nothing, because `Depends` already holds the original function.
3. **Error recording**: `_handle_exception` and `_record_error` schedule `error_history.add` on the running loop. Tests
   reaching them must be `async def` and patch `orchestrator.main.error_history`.
4. **Patch targets** are the modules that use a name: `agents.<agent_name>.main.config`,
   `orchestrator.main._send_task_to_agent`.
5. **Configuration**: override values with `monkeypatch.setattr(config.<Name>Config, "FIELD", value)` or by patching the
   module's `config`; never assign to config globals directly.
6. **Module-global state** such as the agent registry must be reset by a fixture, as `clear_registry` does in
   `tests/orchestrator/test_orchestrator_logic.py`.
7. **Boundaries to mock**: LLM models, MCP toolsets, Jira, Qdrant, test management clients, `httpx`.

## What to cover

Cover what `PYTHON_GUIDELINES.md` § 13 requires. The failure paths this project's code handles explicitly are usually a
raised `HTTPException` status, a returned `AgentExecutionError` and logged-and-continued errors.

Unit tests do not replace the hermetic smoke suite: when a change adds or extends an end-to-end flow, `tests/smoke/`
must be updated too (see *Hermetic smoke suite* in `AGENTS.md`).

## Verify

```bash
uv run pytest tests/<path>/test_<module>.py -v
uv run ruff check tests/<path>/test_<module>.py
uv run pytest
```

All three must pass. If anything fails, continue with the `running-unit-tests` skill.

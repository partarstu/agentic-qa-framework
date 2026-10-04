---
name: adding-orchestrator-workflow
description: Adds a workflow endpoint to the QuAIA orchestrator that receives a webhook or API call, delegates work to agents over A2A and returns the result, including the architecture-first check and the CALM update, models, README docs, orchestrator version bump, unit tests and smoke-suite coverage. Use when creating or extending an orchestrator FastAPI endpoint or multi-agent flow.
---

# Adding an Orchestrator Workflow

Workflow endpoints live in `orchestrator/main.py`. Model new endpoints on the closest existing one:

| Pattern                                         | Reference                                                                 |
|-------------------------------------------------|---------------------------------------------------------------------------|
| Jira webhook → one agent                        | `review_jira_requirements` (`/new-requirements-available`)                |
| Agent task with a structured data part and its own timeout | `trigger_test_case_generation_workflow` (`/story-ready-for-test-case-generation`) with `_request_test_case_design` |
| JSON request model, non-agent service           | `update_jira_db` (`/update-jira-db`), `update_confluence_db` (`/update-confluence-db`), `update_sharepoint_db` (`/update-sharepoint-db`), `update_test_case_db` (`/update-test-case-db`) |
| Exclusive run and parallel fan-out to agents    | `execute_tests` (`/execute-tests`) with `_request_all_test_cases_execution` |
| Explicitly chosen agent, no LLM routing         | `execute_test` (`/execute-test`), reserving the agent under the selection lock |

Copy this checklist and track progress:

```
- [ ] 1. Architecture check (architecture first)
- [ ] 2. Request/result models
- [ ] 3. Endpoint
- [ ] 4. CALM model
- [ ] 5. README documentation
- [ ] 6. Orchestrator version
- [ ] 7. Unit tests
- [ ] 8. Smoke and A/B suites
```

## 1. Architecture check (architecture first)

Decide first whether the workflow alters the topology in `calm/architecture/quaia.arch.json`:

- A new call to a service or external system → a `connects` relationship (or an `interacts` edge for a new agent fan-out).
- A new authentication or protection mechanism → a `controls` block on the node or relationship, asserted in `calm/patterns/quaia.pattern.json`.

Endpoints that reuse existing agents and edges need no change; say so explicitly. When the topology changes, *Architecture first (CALM)* in `AGENTS.md` applies: when the approved plan carries its approval line, continue with step 2; otherwise carry out steps 1-5 of its procedure before anything below. `calm/` itself changes only in step 4.

## 2. Request and result models

Add them to `common/models.py` from [resources/models_template.py](resources/models_template.py). Jira webhook endpoints read the raw `Request` instead and need no request model.

## 3. Endpoint

Start from [resources/endpoint_template.py](resources/endpoint_template.py). Rules:

- Every workflow endpoint takes `api_key: str = Depends(_validate_api_key)`.
- Jira webhook endpoints call `await _verify_jira_webhook_signature(request)` first and read the issue key with `await _get_jira_issue_key_from_request(request)`.
- Workflows that must not overlap run inside `async with execution_lock:`.
- Fan out to agents concurrently as `PYTHON_GUIDELINES.md` § 9 describes.
- If Jira calls the endpoint, add a `<NAME>_WEBHOOK_URL` constant next to the existing ones in `config.py`.

Helpers available in `orchestrator/main.py`:

| Helper                                                                        | Purpose                                                                                     |
|-------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| `_send_task_to_agent(input_data, task_description) -> Task \| None`            | Selects an agent by `task_description` and sends a text task                                 |
| `_send_task_to_agent_with_message(message, task_description, timeout_seconds=None) -> Task \| None`  | Same, with an A2A `Message` (e.g. file or data parts); a given `timeout_seconds` bounds the wait for a free agent and the task together |
| `_get_artifacts_from_task(task, task_description)`                            | Validates the task status and returns its artifacts; raises if there are none                |
| `_validate_task_status(task, task_description)`                               | Status check only, when no artifacts are needed                                              |
| `_get_text_content_from_artifacts(artifacts, task_description, any_content_expected=True)` | Text parts as `list[str]`                                                       |
| `_get_model_from_artifacts(artifacts, task_description, model_type)`          | Parses exactly one text part into `model_type`, or returns `AgentExecutionError`             |
| `_get_file_contents_from_artifacts(artifacts) -> list[FileArtifact]`           | Raw file parts, skipping the token-usage artifact                                            |
| `_handle_exception(message, status_code=500, task_id=None, agent_id=None)`    | Records the error for the dashboard and raises `HTTPException`                               |
| `_record_error(message, task_id=None, agent_id=None)`                         | Records the error without raising; call inside an `except` block                            |

## 4. CALM model

When the topology changes, apply the architecture the user approved in step 1 to `calm/` and validate it (*Commands* in `AGENTS.md`).

## 5. README documentation

Add a subsection under *Invoking Orchestrator Workflows* in `README.md`, in the same format as the existing ones: purpose, method and path, example payload, response.

## 6. Orchestrator version

A new or changed workflow alters the orchestrator's logic, so bump `ORCHESTRATOR_VERSION` (`OrchestratorConfig.VERSION`) as *Versioning* in `AGENTS.md` prescribes.

## 7. Unit tests

Use the `writing-unit-tests` skill and model the tests on `tests/orchestrator/test_endpoints.py`. Cover success, an agent failure or `AgentExecutionError`, and invalid input.

```bash
uv run pytest tests/orchestrator -v
```

## 8. Smoke and A/B suites

A new workflow is a new flow, and a change to what an existing one produces an extended flow: cover it in `tests/smoke/` as *Smoke suite* in `AGENTS.md` requires, with a test that calls the endpoint. The LLM mock (`tests/smoke/mocks/llm_mock.py`) routes a task by its description, so a new task description needs its routing rule there, and every new LLM call its scripted answer. A workflow whose output a model writes gets its own A/B test, and a workflow whose output changes on purpose gets its baseline refreshed, as *A/B suite* in `AGENTS.md` requires.

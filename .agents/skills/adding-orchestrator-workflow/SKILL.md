---
name: adding-orchestrator-workflow
description: Adds a workflow endpoint to the QuAIA orchestrator that receives a webhook or API call, delegates work to agents over A2A and returns the result, including models, README docs, CALM updates, unit tests and smoke-suite coverage. Use when creating or extending an orchestrator FastAPI endpoint or multi-agent flow.
---

# Adding an Orchestrator Workflow

Workflow endpoints live in `orchestrator/main.py`. All Python code follows `PYTHON_GUIDELINES.md`. Model new endpoints
on the closest existing one:

| Pattern                                         | Reference                                                                 |
|-------------------------------------------------|---------------------------------------------------------------------------|
| Jira webhook → one agent                        | `review_jira_requirements` (`/new-requirements-available`)                |
| Sequential multi-agent flow                     | `trigger_test_case_generation_workflow` (`/story-ready-for-test-case-generation`) |
| JSON request model, non-agent service           | `update_rag_db` (`/update-rag-db`)                                        |
| Exclusive run and parallel fan-out to agents    | `execute_tests` (`/execute-tests`) with `_request_all_test_cases_execution` |

Copy this checklist and track progress:

```
- [ ] 1. Request/result models
- [ ] 2. Endpoint
- [ ] 3. README documentation
- [ ] 4. CALM model (if topology changes)
- [ ] 5. Unit tests
- [ ] 6. Smoke suite
```

## 1. Request and result models

Add them to `common/models.py` from [resources/models_template.py](resources/models_template.py). Jira webhook
endpoints read the raw `Request` instead and need no request model.

## 2. Endpoint

Start from [resources/endpoint_template.py](resources/endpoint_template.py). Rules:

- Every workflow endpoint takes `api_key: str = Depends(_validate_api_key)`.
- Jira webhook endpoints call `await _verify_jira_webhook_signature(request)` first and read the issue key with
  `_get_jira_issue_key_from_request(request)`.
- Put `except HTTPException: raise` before `except Exception`. Otherwise the 4xx raised by `_handle_exception` becomes
  a 500 and the error is recorded twice.
- Workflows that must not overlap run inside `async with execution_lock:`.
- Fan out to agents concurrently as `PYTHON_GUIDELINES.md` § 9 describes.
- If Jira calls the endpoint, add a `<NAME>_WEBHOOK_URL` constant next to the existing ones in `config.py`.

Helpers available in `orchestrator/main.py`:

| Helper                                                                        | Purpose                                                                                     |
|-------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| `_send_task_to_agent(input_data, task_description) -> Task \| None`            | Selects an agent by `task_description` and sends a text task                                 |
| `_send_task_to_agent_with_message(message, task_description) -> Task \| None`  | Same, with an A2A `Message` (e.g. file parts)                                                |
| `_get_artifacts_from_task(task, task_description)`                            | Validates the task status and returns its artifacts; raises if there are none                |
| `_validate_task_status(task, task_description)`                               | Status check only, when no artifacts are needed                                              |
| `_get_text_content_from_artifacts(artifacts, task_description, any_content_expected=True)` | Text parts as `list[str]`                                                       |
| `_get_model_from_artifacts(artifacts, task_description, model_type)`          | Parses exactly one text part into `model_type`, or returns `AgentExecutionError`             |
| `_get_file_contents_from_artifacts(artifacts) -> list[FileArtifact]`           | Raw file parts, skipping the token-usage artifact                                            |
| `_handle_exception(message, status_code=500, task_id=None, agent_id=None)`    | Records the error for the dashboard and raises `HTTPException`                               |
| `_record_error(message, task_id=None, agent_id=None)`                         | Records the error without raising; call inside an `except` block                            |

## 3. README documentation

Add a subsection under *Invoking Orchestrator Workflows* in `README.md`, in the same format as the existing ones:
purpose, method and path, example payload, response.

## 4. CALM model

Update `calm/architecture/quaia.arch.json` in the same change when the workflow alters the topology:

- A new call to a service or external system → a `connects` relationship (or an `interacts` edge for a new agent
  fan-out).
- A new authentication or protection mechanism → a `controls` block on the node or relationship, asserted in
  `calm/patterns/quaia.pattern.json`.

Endpoints that reuse existing agents and edges need no change. Validate from `calm/`:

```bash
npx -y "@finos/calm-cli@1.46.0" validate -p patterns/quaia.pattern.json -a architecture/quaia.arch.json -u url-mapping.json --strict -f pretty
```

## 5. Unit tests

Use the `writing-unit-tests` skill and model the tests on `tests/orchestrator/test_endpoints.py`. Cover success, an
agent failure or `AgentExecutionError`, and invalid input.

```bash
uv run pytest tests/orchestrator -v
```

## 6. Smoke suite

A new workflow, or a change to what an existing one produces, is end-to-end behaviour and must be covered in
`tests/smoke/` in the same change:

- **New endpoint** → a test in `tests/smoke/test_smoke.py` (fixtures in `tests/smoke/conftest.py`, recording mocks
  under `tests/smoke/mocks/`) that calls the endpoint and asserts on what reached the mocked boundary.
- **Extended flow** → strengthen the existing assertions.
- **Intentionally changed agent output** → refresh the A/B baseline (see *A/B comparison against a baseline* in
  `README.md`).

The suite needs `GOOGLE_API_KEY` and makes billed LLM calls, so ask the user before running it:

```bash
docker build -t agentic-qa-base:latest -f Dockerfile.base .
docker compose -f docker-compose.smoke.yml up -d --build --wait
uv run pytest tests/smoke -m smoke -v
docker compose -f docker-compose.smoke.yml down -v
```

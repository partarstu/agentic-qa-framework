---
name: creating-new-agent
description: Creates a new A2A agent service in the QuAIA framework - config class, output model, prompts, agent class, Dockerfile, CALM architecture node, unit tests and smoke-suite coverage. Use when the user asks to add a new specialized agent with its own tools, prompts or MCP integrations.
---

# Creating a New Agent

An agent is an A2A service under `agents/<agent_name>/` built on `common.agent_base.AgentBase`.
`agents/requirements_review/` is the reference implementation; the templates below mirror it. All Python code follows
`PYTHON_GUIDELINES.md`.

Copy this checklist and track progress:

```
- [ ] 1. Config class
- [ ] 2. Output model
- [ ] 3. Prompt classes and system prompt
- [ ] 4. Agent class
- [ ] 5. Dockerfile and Cloud Build
- [ ] 6. CALM model
- [ ] 7. Unit tests
- [ ] 8. Smoke suite
- [ ] 9. Agent starts locally
```

Target layout (no `__init__.py`; `agents/` uses namespace packages):

```
agents/<agent_name>/
├── Dockerfile
├── main.py
├── prompt.py
└── system_prompts/
    └── main_prompt_template.txt
```

## 1. Config class

Add a class to `config.py` from [resources/config_template.py](resources/config_template.py):

- `PORT`: pick a default no other agent uses (search `config.py` for `"PORT"`).
- `THINKING_LEVEL`: a pydantic-ai `ThinkingLevel` literal in lowercase, e.g. `"minimal"` or `"medium"`.
- `MODEL_NAME`: keep `DEFAULT_MODEL_NAME` unless the agent needs a different model.
- `VERSION`: read from `<AGENT_NAME>_AGENT_VERSION`; document that variable in the README *Environment Variables*
  block next to the other agent versions.
- `MAX_REQUESTS_PER_TASK`: the tool-call budget per task.
- `SKILL_ID`, `SKILL_NAME`, `SKILL_DESCRIPTION`: the declared skill every agent must have. `AgentBase` requires it
  (there is no generic fallback) and builds the agent card description from model, version and skill name, which the
  orchestrator's routing uses. Keep `SKILL_ID` stable and lower-kebab-case.

## 2. Output model

Add the structured result to `common/models.py` from [resources/output_model_template.py](resources/output_model_template.py).
It must inherit `BaseAgentResult`, which carries `llm_comments` for the model to report gaps or problems.

## 3. Prompt classes and system prompt

- `agents/<agent_name>/prompt.py` from [resources/prompt_template.py](resources/prompt_template.py).
- `agents/<agent_name>/system_prompts/main_prompt_template.txt` from
  [resources/system_prompt_template.txt](resources/system_prompt_template.txt): a numbered task sequence, tools
  described by purpose, and an explicit instruction for what to return when a tool is missing or fails.
- `AgentBase` appends the `report_activity` tool and its instruction automatically. Do not mention it in the template.

## 4. Agent class

Create `agents/<agent_name>/main.py` from [resources/agent_template.py](resources/agent_template.py):

- Pass MCP tools as **factories** (`mcp_toolset_factories=[build_atlassian_mcp_server_toolset]`), never live toolsets:
  `AgentBase` opens a fresh MCP session for every run and closes it afterwards, so a stale session never breaks the
  next request. Omit the argument if the agent needs no MCP tools.
- A sub-agent needing Jira tools opens its own session per run:
  `async with build_atlassian_mcp_server_toolset() as toolset: await sub_agent.run(prompt, toolsets=[toolset])`.
- Custom tools are methods passed via `tools=[...]`. The LLM sees their signature and docstring, so the docstring is
  the tool specification.
- Pass the declared skill via `skill=AgentSkillDeclaration(...)` (required): it becomes the agent card's skill and
  feeds the composed card description.
- Prompt-injection screening, agent registration and activity streaming are handled by `AgentBase`; do not
  reimplement them.
- Module-level `app = agent.a2a_server` is what gunicorn serves.

## 5. Dockerfile and Cloud Build

- `agents/<agent_name>/Dockerfile` from [resources/dockerfile_template](resources/dockerfile_template). It builds on
  `agentic-qa-base:latest` (`docker build -t agentic-qa-base:latest -f Dockerfile.base .`).
- If the agent is deployed to Cloud Run, mirror every `requirements-review-agent` entry in `cloudbuild.yaml`: build,
  push, deploy, and the final `images` list.

## 6. CALM model

A new agent is a new architecture node; the blocking `Architecture (CALM)` CI job fails without it.

1. Add a `node` (`node-type: "service"`) to `calm/architecture/quaia.arch.json`, mirroring the existing agent nodes,
   including the `prompt-injection-guard` control with a unique `control-id`.
2. Add its `unique-id` to the Cloud Run `deployed-in` relationship's `nodes`, plus any new `relationships` it
   introduces (e.g. a call to the embedding service or Qdrant).
3. Assert the node and its control in `calm/patterns/quaia.pattern.json`.
4. Validate from the `calm/` directory; a clean run prints `No issues found.`:
   ```bash
   npx -y "@finos/calm-cli@1.46.0" validate -p patterns/quaia.pattern.json -a architecture/quaia.arch.json -u url-mapping.json --strict -f pretty
   ```

## 7. Unit tests

Create `tests/agents/test_<agent_name>.py` with the `writing-unit-tests` skill. Model construction tests on
`tests/agents/test_requirements_review.py` and custom tool tests on `tests/agents/test_test_case_review.py`.

```bash
uv run pytest tests/agents/test_<agent_name>.py -v
```

## 8. Smoke suite

A new agent is new end-to-end behaviour, so `tests/smoke/` must cover it in the same change:

1. Add a service to `docker-compose.smoke.yml` mirroring `requirements_review` (build, `<<: *agent-env`,
   `AGENT_BASE_URL`, `depends_on`, healthcheck). Add it to the orchestrator's `REMOTE_EXECUTION_AGENT_HOSTS` and
   `depends_on`.
2. If the agent reaches a new external boundary, add or extend a recording mock under `tests/smoke/mocks/`.
3. Add a test to `tests/smoke/test_smoke.py` (fixtures in `tests/smoke/conftest.py`) that drives the agent through the
   orchestrator's public endpoints and asserts on what reached the mocked boundary.

The suite needs `GOOGLE_API_KEY` and makes billed LLM calls, so ask the user before running it:

```bash
docker build -t agentic-qa-base:latest -f Dockerfile.base .
docker compose -f docker-compose.smoke.yml up -d --build --wait
uv run pytest tests/smoke -m smoke -v
docker compose -f docker-compose.smoke.yml down -v
```

## 9. Agent starts locally

From the repository root (running `main.py` as a script cannot import `config`):

```bash
uv run python -m agents.<agent_name>.main
```

The agent card must be served at `http://localhost:<PORT>/.well-known/agent-card.json`.

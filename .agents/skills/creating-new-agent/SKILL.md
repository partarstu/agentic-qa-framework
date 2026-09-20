---
name: creating-new-agent
description: Creates a new A2A agent service in the QuAIA framework - CALM architecture node first, then config class, output model, prompts, agent class, Dockerfile, unit tests and smoke-suite coverage. Use when the user asks to add a new specialized agent with its own tools, prompts or MCP integrations.
---

# Creating a New Agent

An agent is an A2A service under `agents/<agent_name>/` built on `common.agent_base.AgentBase`. There are no code templates: every step names the existing file to mirror. `agents/test_case_classification/` is the smallest complete agent (config, prompt, one custom tool, Dockerfile); `agents/test_case_generation/main.py` shows a sub-agent with its own MCP session per run; `agents/requirements_review/main.py` shows retrieval (RAG) over the vector database. All code follows `PYTHON_GUIDELINES.md` and the *Comments and docstrings* rule of `AGENTS.md`.

Copy this checklist and track progress:

```
- [ ] 1. CALM model (architecture first)
- [ ] 2. Config class
- [ ] 3. Output model
- [ ] 4. Prompt class and system prompt
- [ ] 5. Agent class
- [ ] 6. Dockerfile and Cloud Build
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
    └── main_prompt_template.md
```

## 1. CALM model (architecture first)

A new agent is a new architecture node, and *Architecture first* in `AGENTS.md` fixes the order: model, validate, render, approval, then code. Nothing below is written before the user has approved the architecture.

1. Add a `node` (`node-type: "service"`) to `calm/architecture/quaia.arch.json`, mirroring the existing agent nodes, including the `prompt-injection-guard` control with a unique `control-id`.
2. Add its `unique-id` to the Cloud Run `deployed-in` relationship's `nodes`, plus every new `relationship` it introduces (e.g. a call to the embedding service or Qdrant).
3. Assert the node and its control in `calm/patterns/quaia.pattern.json`.
4. Validate from the `calm/` directory; a clean run prints `No issues found.`:
   ```bash
   npx -y "@finos/calm-cli@1.46.0" validate -p patterns/quaia.pattern.json -a architecture/quaia.arch.json -u url-mapping.json --strict -f pretty
   ```
5. Render the documentation with `npx -y @finos/calm-cli@1.46.0 docify -a architecture/quaia.arch.json -o <directory outside the repository>`, show the user the diagram and pages, and get their explicit approval.

## 2. Config class

Add a `<AgentName>AgentConfig` class to `config.py`, mirroring `TestCaseClassificationAgentConfig`:

- `PORT`: pick a default no other agent uses (search `config.py` for `"PORT"`).
- `THINKING_LEVEL`: a pydantic-ai `ThinkingLevel` literal in lowercase, e.g. `"minimal"` or `"medium"`.
- `MODEL_NAME`: keep `DEFAULT_MODEL_NAME` unless the agent needs a different model.
- `VERSION`: read from `<AGENT_NAME>_AGENT_VERSION` with the default `"1.0.0"` (*Versioning of agents and the orchestrator* in `AGENTS.md`); document the variable in the README *Environment Variables* block next to the other agent versions.
- `MAX_REQUESTS_PER_TASK`: the tool-call budget per task.
- `SKILL_ID`, `SKILL_NAME`, `SKILL_DESCRIPTION`: the declared skill every agent must have. `AgentBase` requires it and builds the agent card description from model, version and skill name, which the orchestrator's routing uses. Keep `SKILL_ID` stable and lower-kebab-case.

## 3. Output model

Add the structured result to `common/models.py`, mirroring `ClassifiedTestCases`. It must inherit `BaseAgentResult`, which carries `llm_comments` for the model to report gaps or problems.

## 4. Prompt class and system prompt

- `agents/<agent_name>/prompt.py`, mirroring `agents/requirements_review/prompt.py`: a `PromptBase` subclass whose `get_script_dir()` points at the agent's `system_prompts/` directory and whose default template name is `main_prompt_template.md` (the classification agent keeps its template next to `prompt.py` instead, so it is not the mirror for this file).
- `agents/<agent_name>/system_prompts/main_prompt_template.md` from [resources/system_prompt_template.md](resources/system_prompt_template.md): the `# Input` section is mandatory; Markdown with headings, a numbered task sequence and fenced examples (escape literal braces as `{{`/`}}` when the prompt class formats placeholders), tools described by purpose, and an explicit instruction for what to return when a tool is missing or fails.
- `AgentBase` appends the `report_activity` tool and its instruction automatically. Do not mention it in the template.

## 5. Agent class

Create `agents/<agent_name>/main.py`, mirroring `agents/test_case_classification/main.py`:

- Build the Jira tool allowlist from the constants in `common/services/atlassian_tools.py` (`JIRA_GET_ISSUE`, `JIRA_ADD_COMMENT`, `JIRA_CREATE_ISSUE`, `JIRA_UPDATE_ISSUE`), never from string literals, and always pass it: the combined server also advertises Confluence tools, and an agent must not receive tools it was not built for. An agent that needs no Atlassian tool passes an empty tuple.
- Pass MCP tools as **factories** (`mcp_toolset_factories=[lambda: build_atlassian_mcp_server_toolset(_JIRA_TOOL_ALLOWLIST)]`), never live toolsets: `AgentBase` opens a fresh MCP session for every run and closes it afterwards. Omit the argument if the agent needs no MCP tools.
- A sub-agent needing Jira tools opens its own session per run, as `agents/test_case_generation/main.py` does with `async with build_atlassian_mcp_server_toolset(...) as toolset: await sub_agent.run(prompt, toolsets=[toolset])`.
- Retrieval over the vector database follows `agents/requirements_review/main.py` (`common.services.document_retrieval` and `VectorDbService`).
- Custom tools are methods passed via `tools=[...]`. The LLM sees their signature and docstring, so the docstring is the tool specification and keeps its `Args` and `Returns` (the one place the comment rule requires them).
- A tool takes every value it needs as its own parameter, which the model fills from the task text (e.g. a Jira issue key). `AgentBase` runs the agent without dependencies, so a tool reading `ctx.deps` fails at its first call; do not declare `deps_type` (the classification agent's `deps_type=TestCaseKeys` is unused and not part of the pattern to mirror).
- Pass the declared skill via `skill=AgentSkillDeclaration(...)` (required): it becomes the agent card's skill and feeds the composed card description.
- Prompt-injection screening, agent registration and activity streaming are handled by `AgentBase`; do not reimplement them.
- Module-level `app = agent.a2a_server` is what gunicorn serves.

## 6. Dockerfile and Cloud Build

- `agents/<agent_name>/Dockerfile`, copied from `agents/test_case_classification/Dockerfile` with the module path changed. It builds on `agentic-qa-base:latest` (`docker build -t agentic-qa-base:latest -f Dockerfile.base .`).
- If the agent is deployed to Cloud Run, mirror every `requirements-review-agent` entry in `cloudbuild.yaml`: build, push, deploy, and the final `images` list.

## 7. Unit tests

Create `tests/agents/test_<agent_name>.py` with the `writing-unit-tests` skill. Model construction tests on `tests/agents/test_requirements_review.py` and custom tool tests on `tests/agents/test_test_case_review.py`.

```bash
uv run pytest tests/agents/test_<agent_name>.py -v
```

## 8. Smoke suite

A new agent is new end-to-end behaviour, so `tests/smoke/` must cover it in the same change:

1. Add a service to `docker-compose.smoke.yml` mirroring `requirements_review` (build, `<<: *agent-env`, `AGENT_BASE_URL`, `depends_on`, healthcheck). Add it to the orchestrator's `REMOTE_EXECUTION_AGENT_HOSTS` and `depends_on`.
2. If the agent reaches a new external boundary, add or extend a recording mock under `tests/smoke/mocks/`.
3. Add a test to `tests/smoke/test_smoke.py` (fixtures in `tests/smoke/conftest.py`) that drives the agent through the orchestrator's public endpoints and asserts on what reached the mocked boundary.

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

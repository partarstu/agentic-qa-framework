---
name: creating-new-agent
description: Creates a new A2A agent service in the QuAIA framework - architecture check first, then config class, output model, prompts, agent class, Dockerfile, CALM node, unit tests and smoke-suite coverage. Use when the user asks to add a new specialized agent with its own tools, prompts or MCP integrations.
---

# Creating a New Agent

An agent is an A2A service under `agents/<agent_name>/` built on `common.agent_base.AgentBase`. There are no code templates: every step names the existing file to mirror. `agents/test_case_classification/main.py` is the smallest agent class (config, prompt, one custom tool), though it runs only in-process inside the Test Case Design agent, so `agents/incident_creation/` shows the deployed parts (module-level `app`, Dockerfile); `agents/test_case_design/main.py` shows an agent whose MCP tool stores its result in the run's dependencies; `agents/requirements_review/main.py` shows retrieval (RAG) over the vector database.

Copy this checklist and track progress:

```
- [ ] 1. Architecture check (architecture first)
- [ ] 2. Config class
- [ ] 3. Output model
- [ ] 4. Prompt class and system prompt
- [ ] 5. Agent class
- [ ] 6. Dockerfile and Cloud Build
- [ ] 7. CALM model
- [ ] 8. Unit tests
- [ ] 9. Smoke suite
- [ ] 10. Agent starts locally
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

## 1. Architecture check (architecture first)

A new agent is a new architecture node, so *Architecture first (CALM)* in `AGENTS.md` applies: when the approved plan carries its approval line, continue with step 2; otherwise carry out steps 1-5 of its procedure for the elements of step 7 before anything below. `calm/` itself changes only in step 7.

## 2. Config class

Add a `<AgentName>AgentConfig` class to `config.py`, mirroring `TestCaseClassificationAgentConfig`:

- `PORT`: pick a default no other agent uses (search `config.py` for `"PORT"`).
- `THINKING_LEVEL`: a pydantic-ai `ThinkingLevel` literal in lowercase, e.g. `"minimal"` or `"medium"`.
- `MODEL_NAME`: keep `DEFAULT_MODEL_NAME` unless the agent needs a different model.
- `VERSION`: read from `<AGENT_NAME>_AGENT_VERSION` with the default `"1.0.0"`; document the variable in the README *Environment Variables* block next to the other agent versions.
- `MAX_REQUESTS_PER_TASK`: the tool-call budget per task.
- `SKILL_ID`, `SKILL_NAME`, `SKILL_DESCRIPTION`: the declared skill every agent must have. `AgentBase` requires it and builds the agent card description from model, version and skill name, which the orchestrator's routing uses. Keep `SKILL_ID` stable and lower-kebab-case.

## 3. Output model

Add the structured result to `common/models.py`, mirroring `ClassifiedTestCases`. Its base `BaseAgentResult` carries `llm_comments` for the model to report gaps or problems.

## 4. Prompt class and system prompt

- `agents/<agent_name>/prompt.py`, mirroring `agents/requirements_review/prompt.py`: a `PromptBase` subclass whose `get_script_dir()` points at the agent's `system_prompts/` directory and whose default template name is `main_prompt_template.md` (the classification agent keeps its template next to `prompt.py` instead, so it is not the mirror for this file).
- `agents/<agent_name>/system_prompts/main_prompt_template.md` from [resources/system_prompt_template.md](resources/system_prompt_template.md): the `# Input` section is mandatory; Markdown with headings, a numbered task sequence and fenced examples (escape literal braces as `{{`/`}}` when the prompt class formats placeholders), tools described by purpose, and an explicit instruction for what to return when a tool is missing or fails.

## 5. Agent class

Create `agents/<agent_name>/main.py`, mirroring `agents/test_case_classification/main.py`:

- Build the Jira tool allowlist from the constants in `common/services/atlassian_tools.py` (`JIRA_GET_ISSUE`, `JIRA_ADD_COMMENT`, `JIRA_CREATE_ISSUE`, `JIRA_UPDATE_ISSUE`), never from string literals, and always pass it: the combined server also advertises Confluence tools, and an agent must not receive tools it was not built for. An agent that needs no Atlassian tool passes an empty tuple.
- Pass MCP tools as factories, `mcp_toolset_factories=[lambda: build_atlassian_mcp_server_toolset(_JIRA_TOOL_ALLOWLIST)]`: `AgentBase` opens a fresh MCP session for every run and closes it afterwards. Omit the argument if the agent needs no MCP tools.
- A sub-agent needing Jira tools opens its own session per run, as `agents/test_case_generation/main.py` does with `async with build_atlassian_mcp_server_toolset(...) as toolset: await sub_agent.run(prompt, toolsets=[toolset])`.
- Retrieval over the vector database follows `agents/requirements_review/main.py` (`common.services.document_retrieval` and `VectorDbService`).
- Custom tools are methods passed via `tools=[...]`; the LLM reads their signature and docstring as the tool specification.
- A tool takes every value it needs as its own parameter, which the model fills from the task text (e.g. a Jira issue key). `AgentBase` gives a task run dependencies only when the agent declares `deps_type` and the task message carries a structured data part, as the Test Case Design agent's request does; a text-driven agent declares no `deps_type`, and its tools never read `ctx.deps` (the classification agent's `deps_type=TestCaseKeys` is not read by its tool and not part of the pattern to mirror).
- Pass the declared skill via `skill=AgentSkillDeclaration(...)` (required): it becomes the agent card's skill and feeds the composed card description.
- Module-level `app = agent.a2a_server` is what gunicorn serves.

## 6. Dockerfile and Cloud Build

- `agents/<agent_name>/Dockerfile`, copied from `agents/incident_creation/Dockerfile` with the module path changed. It builds on `agentic-qa-base:latest` (`docker build -t agentic-qa-base:latest -f Dockerfile.base .`).
- If the agent is deployed to Cloud Run, mirror every `requirements-review-agent` entry in `cloudbuild.yaml`: build, push, deploy, and the final `images` list.

## 7. CALM model

Apply the architecture the user approved in step 1 to `calm/`:

1. Add a `node` (`node-type: "service"`) to `calm/architecture/quaia.arch.json`, mirroring the existing agent nodes, including the `prompt-injection-guard` control with a unique `control-id`.
2. Add its `unique-id` to the Cloud Run `deployed-in` relationship's `nodes`, plus every new `relationship` it introduces (e.g. a call to the embedding service or Qdrant).
3. Assert the node and its control in `calm/patterns/quaia.pattern.json`.
4. Validate (*Commands* in `AGENTS.md`).

## 8. Unit tests

Create `tests/agents/test_<agent_name>.py` with the `writing-unit-tests` skill. Model construction tests on `tests/agents/test_requirements_review.py` and custom tool tests on `tests/agents/test_test_case_review.py`.

```bash
uv run pytest tests/agents/test_<agent_name>.py -v
```

## 9. Smoke suite

A new agent is a new flow, so `tests/smoke/` covers it in the same change as *Smoke suite* in `AGENTS.md` requires. The agent also needs its own service in `docker-compose.smoke.yml`, mirroring `requirements_review` (build, `<<: *agent-env`, `AGENT_BASE_URL`, `depends_on`, healthcheck), added to the orchestrator's `REMOTE_EXECUTION_AGENT_HOSTS` and `depends_on`.

## 10. Agent starts locally

From the repository root (running `main.py` as a script cannot import `config`):

```bash
uv run python -m agents.<agent_name>.main
```

The agent card must be served at `http://localhost:<PORT>/.well-known/agent-card.json`.

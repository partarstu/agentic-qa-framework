---
name: creating-new-agent
description: Creates new A2A-compliant agents in the QuAIA framework. Use when adding a new specialized agent with custom tools, prompts, and MCP server integrations.
---

// turbo-all

# Creating a New Agent

This skill provides a comprehensive guide for creating a new specialized agent in the QuAIA™ framework. Agents are A2A-compliant (Agent-to-Agent protocol) services that handle specific QA-related tasks.

## Overview

Each agent in QuAIA consists of:
1. **Main module** (`main.py`) - Agent class inheriting from `AgentBase`
2. **Prompt module** (`prompt.py`) - Prompt classes inheriting from `PromptBase`
3. **System prompts** (`system_prompts/`) - Text template files for LLM instructions
4. **Dockerfile** - Container configuration for deployment
5. **Configuration** - Class in `config.py` for agent-specific settings
6. **Unit tests** - Test file in `tests/agents/`

## ⚡ Auto-Run Policy

This skill is designed to run with minimal interruption.

- **Always set `SafeToAutoRun: true`** for all `run_command` calls.
- **Exceptions:** Only set `SafeToAutoRun: false` if a step specifically instructs you to "Ask" the user, "Wait" for approval, or "Verify" a destructive action before proceeding.
- **Restricted Symbols:** Never use the redirection operator (`>`) or `2>` in commands. Use alternatives (e.g., `Set-Content`, `Out-File`, or ignoring errors explicitly).

## Step-by-Step Instructions

### Step 1: Create the Agent Directory Structure

Create a new directory under `agents/` with the following structure:

```
agents/<agent_name>/
├── __init__.py (empty file)
├── main.py
├── prompt.py
├── Dockerfile
└── system_prompts/
    └── main_prompt_template.txt
```

**Example command:**
```bash
mkdir -p agents/<agent_name>/system_prompts
```

### Step 2: Define the Configuration Class

Add a configuration class in `config.py` using the template:

📄 **Template:** [resources/config_template.py](resources/config_template.py)

**Configuration field descriptions:**
- `THINKING_LEVEL`: Thinking level for chain-of-thought reasoning ("MINIMAL" disables it or keeps it to minimum)
- `OWN_NAME`: Human-readable name displayed in the orchestrator dashboard
- `PORT`: Internal container port the agent listens on
- `EXTERNAL_PORT`: Externally accessible port (usually same as PORT)
- `MODEL_NAME`: The LLM model to use (format: `provider:model-name`)
- `MAX_REQUESTS_PER_TASK`: Limit on tool/MCP calls per task execution

### Step 3: Define the Output Model

If the agent returns structured output, add a Pydantic model in `common/models.py`:

📄 **Template:** [resources/output_model_template.py](resources/output_model_template.py)

**Important:** Inherit from `BaseAgentResult` to include the `llm_comments` field for debugging.

### Step 4: Create the Prompt Classes

Create `agents/<agent_name>/prompt.py`:

📄 **Template:** [resources/prompt_template.py](resources/prompt_template.py)

### Step 5: Create the System Prompt Template

Create `agents/<agent_name>/system_prompts/main_prompt_template.txt`:

📄 **Template:** [resources/system_prompt_template.txt](resources/system_prompt_template.txt)

**Best practices for prompts:**
- Be specific about the expected workflow
- List tasks in numbered sequence
- Include error handling instructions
- Reference tools by describing their purpose, not implementation

### Step 6: Create the Agent Class

Create `agents/<agent_name>/main.py`:

📄 **Template:** [resources/agent_template.py](resources/agent_template.py)

**Key points:**
- The agent class MUST inherit from `AgentBase`
- Implement `get_thinking_level()` and `get_max_requests_per_task()`
- Custom tools are defined as methods with full docstrings (LLM uses these)
- The `app` variable exposes the A2A-compliant FastAPI application
- `start_as_server()` runs the agent standalone with uvicorn

### Step 7: Create the Dockerfile

Create `agents/<agent_name>/Dockerfile`:

📄 **Template:** [resources/dockerfile_template](resources/dockerfile_template)

### Step 8: Update Cloud Build Configuration (Optional)

If deploying to Google Cloud Run, add build and deploy steps to `cloudbuild.yaml`:

1. Add a build step for the Docker image
2. Add a push step for the image
3. Add a deploy step for Cloud Run

### Step 9: Register the Agent in the CALM Architecture Model

The architecture is maintained as code with [FINOS CALM](https://calm.finos.org/) under `calm/`, and a **blocking** CI
job validates it. A new agent is a new architecture node, so the model must be updated in the same change or the
`Architecture (CALM)` CI job will fail.

1. Add the agent as a `node` (`node-type: "service"`) in `calm/architecture/quaia.arch.json`, mirroring the existing
   agent nodes. Give it the same `prompt-injection-guard` control block (with a unique `control-id`), since every agent
   screens its input through the prompt guard service.
2. Add the agent's `unique-id` to the `deployed-in` Cloud Run relationship's `nodes` list, plus any new
   `relationships` it introduces (e.g. a new call to the embedding service or Qdrant).
3. Add the agent (and its required control) to the `nodes` assertions in `calm/patterns/quaia.pattern.json` so its
   presence is enforced.
4. Validate locally from the `calm/` directory:
   ```bash
   npx -y @finos/calm-cli@1.46.0 validate -p patterns/quaia.pattern.json -a architecture/quaia.arch.json -u url-mapping.json --strict -f pretty
   ```
   A clean run prints `No issues found.` See `calm/README.md` for details.

### Step 10: Create Unit Tests

Create `tests/agents/test_<agent_name>.py`:

📄 **Example:** [examples/test_agent_example.py](examples/test_agent_example.py)

### Step 11: Extend the Hermetic Smoke Suite

The smoke suite under `tests/smoke/` exercises the whole system end-to-end against the real orchestrator and agents in
`docker-compose.smoke.yml`, and the `smoke` CI job runs it. A new agent is new end-to-end behaviour, so the smoke suite
**must** be updated in the same change — it is not optional.

1. Add the agent to the `docker-compose.smoke.yml` topology so it starts and registers with the orchestrator, mirroring
   the existing agent services.
2. If the agent reaches an external boundary, add or extend a recording mock under `tests/smoke/mocks/` so its effect is
   captured.
3. Add a smoke test in `tests/smoke/test_smoke.py` (plus any fixtures it needs in `tests/smoke/conftest.py`) that drives
   the agent through the orchestrator's public webhooks and asserts on what reached the mocked boundary, following the
   existing tests.
4. Run the suite with the stack up:
   ```bash
   docker build -t agentic-qa-base:latest -f Dockerfile.base .
   GOOGLE_API_KEY=<your-key> docker compose -f docker-compose.smoke.yml up -d --build
   uv run pytest tests/smoke -m smoke -v
   docker compose -f docker-compose.smoke.yml down -v
   ```

## Verification Checklist

After creating the agent, verify:

- [ ] Agent directory structure is complete
- [ ] Configuration class added to `config.py`
- [ ] Output model (if any) added to `common/models.py`
- [ ] Prompt class properly inherits from `PromptBase`
- [ ] System prompt template exists and is well-structured
- [ ] Agent class properly inherits from `AgentBase`
- [ ] Dockerfile follows the standard pattern
- [ ] Agent registered as a node (with its `prompt-injection-guard` control) in `calm/architecture/quaia.arch.json` and asserted in `calm/patterns/quaia.pattern.json`
- [ ] CALM validation passes: `npx -y @finos/calm-cli@1.46.0 validate -p patterns/quaia.pattern.json -a architecture/quaia.arch.json -u url-mapping.json --strict` (from `calm/`)
- [ ] Unit tests pass: `pytest tests/agents/test_<agent_name>.py -v`
- [ ] Smoke suite extended: the agent runs in `docker-compose.smoke.yml` and a `tests/smoke/` test asserts its end-to-end behaviour
- [ ] Agent starts successfully: `python agents/<agent_name>/main.py`
- [ ] Agent card is discoverable at `http://localhost:<port>/.well-known/agent.json`

## Running the Agent Locally

```bash
# Activate virtual environment
.venv\Scripts\activate

# Run the agent
python agents/<agent_name>/main.py
```

The agent will start listening on the configured port and automatically expose:
- `/.well-known/agent.json` - Agent card for discovery
- A2A task endpoints for receiving and processing tasks

---
name: creating-new-agent
description: Creates new A2A-compliant agents in the QuAIA framework. Use when adding a new specialized agent with custom tools, prompts, and MCP server integrations.
---

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
- `THINKING_BUDGET`: Token budget for chain-of-thought reasoning (0 disables it)
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
- Implement `get_thinking_budget()` and `get_max_requests_per_task()`
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

### Step 9: Create Unit Tests

Create `tests/agents/test_<agent_name>.py`:

📄 **Example:** [examples/test_agent_example.py](examples/test_agent_example.py)

## Verification Checklist

After creating the agent, verify:

- [ ] Agent directory structure is complete
- [ ] Configuration class added to `config.py`
- [ ] Output model (if any) added to `common/models.py`
- [ ] Prompt class properly inherits from `PromptBase`
- [ ] System prompt template exists and is well-structured
- [ ] Agent class properly inherits from `AgentBase`
- [ ] Dockerfile follows the standard pattern
- [ ] Unit tests pass: `pytest tests/agents/test_<agent_name>.py -v`
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

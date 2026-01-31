---
name: Creating a New Agent
description: Step-by-step guide for creating a new specialized agent in the QuAIA framework
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

Add a configuration class in `config.py`:

```python
class <AgentName>AgentConfig:
    THINKING_BUDGET = 2000  # Token budget for thinking (0 to disable)
    OWN_NAME = "<Human-Readable Agent Name>"
    PORT = int(os.environ.get("PORT", "<unique_port>"))  # e.g., 8008
    EXTERNAL_PORT = int(os.environ.get("EXTERNAL_PORT", PORT))
    PROTOCOL = "http"
    MODEL_NAME = "google-gla:gemini-3-flash-preview"
    MAX_REQUESTS_PER_TASK = 30  # Maximum tool calls per task
```

**Configuration field descriptions:**
- `THINKING_BUDGET`: Token budget for chain-of-thought reasoning (0 disables it)
- `OWN_NAME`: Human-readable name displayed in the orchestrator dashboard
- `PORT`: Internal container port the agent listens on
- `EXTERNAL_PORT`: Externally accessible port (usually same as PORT)
- `MODEL_NAME`: The LLM model to use (format: `provider:model-name`)
- `MAX_REQUESTS_PER_TASK`: Limit on tool/MCP calls per task execution

### Step 3: Define the Output Model

If the agent returns structured output, add a Pydantic model in `common/models.py`:

```python
class <AgentOutput>(BaseAgentResult):
    """Result from <Agent Name> agent."""
    
    field_name: str = Field(description="Description of this field")
    # Add other fields as needed
```

**Important:** Inherit from `BaseAgentResult` to include the `llm_comments` field for debugging.

### Step 4: Create the Prompt Classes

Create `agents/<agent_name>/prompt.py`:

```python
# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from common import utils
from common.prompt_base import PromptBase

logger = utils.get_logger("<agent_name>.agent")
PROMPTS_ROOT = "system_prompts"


def _get_prompts_root() -> Path:
    return Path(__file__).resolve().parent.joinpath(PROMPTS_ROOT)


class <AgentName>SystemPrompt(PromptBase):
    """
    Loads the main system prompt template for <Agent Name>.
    """

    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(
        self,
        # Add any template variables as constructor parameters
        template_file_name: str = "main_prompt_template.txt"
    ):
        """
        Initializes the prompt instance.

        Args:
            template_file_name: The name of the prompt template file.
        """
        super().__init__(template_file_name)
        # Store template variables for formatting

    def get_prompt(self) -> str:
        """Returns the formatted prompt as a string."""
        logger.info("Generating <agent_name> system prompt")
        # Return template with variables substituted
        return self.template.format(
            # variable_name=self.variable_name
        )
```

### Step 5: Create the System Prompt Template

Create `agents/<agent_name>/system_prompts/main_prompt_template.txt`:

```text
You are a specialized agent for <describe the agent's purpose>.

Your tasks:
1. <First task the agent should perform>
2. <Second task>
3. <etc.>

Guidelines:
- <Important guideline 1>
- <Important guideline 2>

If you encounter any issues or cannot find required tools, return immediately with a detailed error description.
```

**Best practices for prompts:**
- Be specific about the expected workflow
- List tasks in numbered sequence
- Include error handling instructions
- Reference tools by describing their purpose, not implementation

### Step 6: Create the Agent Class

Create `agents/<agent_name>/main.py`:

```python
# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from pydantic_ai.mcp import MCPServerSSE

import config
from agents.<agent_name>.prompt import <AgentName>SystemPrompt
from common import utils
from common.agent_base import AgentBase
from common.models import <OutputModel>, <DepsModel>  # Import relevant models

logger = utils.get_logger("<agent_name>_agent")

# Add MCP servers if the agent needs external tools
# jira_mcp_server = MCPServerSSE(url=config.JIRA_MCP_SERVER_URL, timeout=config.MCP_SERVER_TIMEOUT_SECONDS)


class <AgentName>Agent(AgentBase):
    def __init__(self):
        instruction_prompt = <AgentName>SystemPrompt(
            # Pass any template variables
        )
        super().__init__(
            agent_name=config.<AgentName>AgentConfig.OWN_NAME,
            base_url=config.AGENT_BASE_URL,
            port=config.<AgentName>AgentConfig.PORT,
            external_port=config.<AgentName>AgentConfig.EXTERNAL_PORT,
            protocol=config.<AgentName>AgentConfig.PROTOCOL,
            model_name=config.<AgentName>AgentConfig.MODEL_NAME,
            output_type=<OutputModel>,  # The Pydantic model for structured output
            instructions=instruction_prompt.get_prompt(),
            mcp_servers=[],  # Add MCP servers here if needed
            deps_type=<DepsModel>,  # Optional: context/dependencies type
            description="<Brief description of what this agent does>",
            tools=[self.<custom_tool>]  # Add custom tools here
            # vector_db_collection_name="<collection>"  # For RAG-enabled agents
        )

    def get_thinking_budget(self) -> int:
        return config.<AgentName>AgentConfig.THINKING_BUDGET

    def get_max_requests_per_task(self) -> int:
        return config.<AgentName>AgentConfig.MAX_REQUESTS_PER_TASK

    # Define custom tools as methods with docstrings
    async def <custom_tool>(self, param: str) -> str:
        """
        Brief description of what this tool does.

        Args:
            param: Description of the parameter.

        Returns:
            Description of the return value.
        """
        # Tool implementation
        return "result"


# Create agent instance and expose FastAPI app
agent = <AgentName>Agent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()
```

**Key points:**
- The agent class MUST inherit from `AgentBase`
- Implement `get_thinking_budget()` and `get_max_requests_per_task()`
- Custom tools are defined as methods with full docstrings (LLM uses these)
- The `app` variable exposes the A2A-compliant FastAPI application
- `start_as_server()` runs the agent standalone with uvicorn

### Step 7: Create the Dockerfile

Create `agents/<agent_name>/Dockerfile`:

```dockerfile
# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0
FROM agentic-qa-base:latest

ARG WORK_DIR=/app
WORKDIR ${WORK_DIR}

COPY agents/<agent_name>/ ${WORK_DIR}/agents/<agent_name>
COPY common/ ${WORK_DIR}/common
COPY config.py ${WORK_DIR}/config.py

CMD gunicorn -w 1 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT agents.<agent_name>.main:app
```

### Step 8: Update Cloud Build Configuration (Optional)

If deploying to Google Cloud Run, add build and deploy steps to `cloudbuild.yaml`:

1. Add a build step for the Docker image
2. Add a push step for the image
3. Add a deploy step for Cloud Run

### Step 9: Create Unit Tests

Create `tests/agents/test_<agent_name>.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

import config
from agents.<agent_name>.main import <AgentName>Agent


@pytest.fixture
def mock_config(monkeypatch):
    monkeypatch.setattr(config.<AgentName>AgentConfig, "OWN_NAME", "Test Agent")
    monkeypatch.setattr(config.<AgentName>AgentConfig, "PORT", 8099)
    monkeypatch.setattr(config.<AgentName>AgentConfig, "EXTERNAL_PORT", 8099)
    monkeypatch.setattr(config.<AgentName>AgentConfig, "PROTOCOL", "http")
    monkeypatch.setattr(config.<AgentName>AgentConfig, "MODEL_NAME", "test")
    monkeypatch.setattr(config.<AgentName>AgentConfig, "THINKING_BUDGET", 100)
    monkeypatch.setattr(config.<AgentName>AgentConfig, "MAX_REQUESTS_PER_TASK", 5)
    monkeypatch.setattr(config, "AGENT_BASE_URL", "http://localhost")


@patch("agents.<agent_name>.main.<AgentName>SystemPrompt")
@patch("agents.<agent_name>.main.AgentBase.__init__")
def test_agent_init(mock_super_init, mock_prompt_cls, mock_config):
    mock_prompt_instance = MagicMock()
    mock_prompt_instance.get_prompt.return_value = "system prompt"
    mock_prompt_cls.return_value = mock_prompt_instance

    agent = <AgentName>Agent()

    mock_super_init.assert_called_once()
    _, kwargs = mock_super_init.call_args
    assert kwargs["agent_name"] == "Test Agent"
    assert kwargs["instructions"] == "system prompt"

    assert agent.get_thinking_budget() == 100
    assert agent.get_max_requests_per_task() == 5
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

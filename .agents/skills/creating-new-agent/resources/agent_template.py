# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""
Agent class template for a new agent.

Replace <agent_name> with your agent's folder name (e.g., requirements_review).
Replace <AgentName> with your agent's class name (e.g., RequirementsReview).
Replace <OutputModel> with the Pydantic model for structured output.
Replace <DepsModel> with the context/dependencies type (optional).
"""

import config
from agents.<agent_name>.prompt import <AgentName>SystemPrompt
from common import utils
from common.agent_base import AgentBase
from common.models import <OutputModel>, <DepsModel>  # Import relevant models
from common.services.jira_mcp import build_jira_mcp_server_toolset

logger = utils.get_logger("<agent_name>_agent")


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
            version=config.<AgentName>AgentConfig.VERSION,
            output_type=<OutputModel>,  # The Pydantic model for structured output
            instructions=instruction_prompt.get_prompt(),
            # Factories, not live connections: one fresh MCP session is built per agent run and closed
            # with it. Drop this argument if the agent needs no MCP tools.
            mcp_toolset_factories=[build_jira_mcp_server_toolset],
            deps_type=<DepsModel>,  # Optional: context/dependencies type
            description="<Brief description of what this agent does>",
            tools=[self.<custom_tool>]  # Add custom tools here
            # vector_db_collection_name="<collection>"  # For RAG-enabled agents
        )

    def get_thinking_level(self) -> str:
        return config.<AgentName>AgentConfig.THINKING_LEVEL

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

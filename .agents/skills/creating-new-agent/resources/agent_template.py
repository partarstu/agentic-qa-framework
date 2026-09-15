# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""
Agent class template for a new agent.

Replace <agent_name> with the folder name (e.g. requirements_review), <AgentName> with the class prefix
(e.g. RequirementsReview), <OutputModel> with the result model and <DepsModel> with the dependencies model.
"""

from pydantic_ai.settings import ThinkingLevel

import config
from agents.<agent_name>.prompt import <AgentName>SystemPrompt
from common import utils
from common.agent_base import AgentBase
from common.models import <DepsModel>, <OutputModel>
from common.services.jira_mcp import build_jira_mcp_server_toolset

logger = utils.get_logger("<agent_name>_agent")


class <AgentName>Agent(AgentBase):
    """<One-line description of what the agent does>."""

    def __init__(self):
        instruction_prompt = <AgentName>SystemPrompt()
        super().__init__(
            agent_name=config.<AgentName>AgentConfig.OWN_NAME,
            base_url=config.AGENT_BASE_URL,
            port=config.<AgentName>AgentConfig.PORT,
            external_port=config.<AgentName>AgentConfig.EXTERNAL_PORT,
            protocol=config.<AgentName>AgentConfig.PROTOCOL,
            model_name=config.<AgentName>AgentConfig.MODEL_NAME,
            version=config.<AgentName>AgentConfig.VERSION,
            output_type=<OutputModel>,
            instructions=instruction_prompt.get_prompt(),
            # Drop if the agent needs no MCP tools.
            mcp_toolset_factories=[build_jira_mcp_server_toolset],
            # Optional: drop if the agent needs no typed dependencies.
            deps_type=<DepsModel>,
            description="<Brief description used by the orchestrator to select this agent>",
            tools=[self.<custom_tool>],
            # vector_db_collection_name="<collection>",  # only for RAG-enabled agents
        )

    def get_thinking_level(self) -> ThinkingLevel:
        return config.<AgentName>AgentConfig.THINKING_LEVEL

    def get_max_requests_per_task(self) -> int:
        return config.<AgentName>AgentConfig.MAX_REQUESTS_PER_TASK

    async def <custom_tool>(self, param: str) -> str:
        """
        <What the tool does - the LLM reads this docstring as the tool specification>.

        Args:
            param: <Description of the parameter>.

        Returns:
            <Description of the return value>.
        """
        ...


agent = <AgentName>Agent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()

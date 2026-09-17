# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""
Agent class template for a new agent.

Replace <agent_name> with the folder name (e.g. requirements_review), <AgentName> with the class prefix
(e.g. RequirementsReview) and <OutputModel> with the result model.
"""

from pydantic_ai.settings import ThinkingLevel

import config
from agents.<agent_name>.prompt import <AgentName>SystemPrompt
from common import utils
from common.agent_base import AgentBase
from common.models import AgentSkillDeclaration, <OutputModel>
from common.services.atlassian_mcp import build_atlassian_mcp_server_toolset

logger = utils.get_logger("<agent_name>_agent")

# The Atlassian MCP server advertises Jira and Confluence tools alike; list only the tools this agent uses.
_ATLASSIAN_TOOL_ALLOWLIST = ("jira_get_issue", "<other_tool_name>")


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
            mcp_toolset_factories=[lambda: build_atlassian_mcp_server_toolset(_ATLASSIAN_TOOL_ALLOWLIST)],
            skill=AgentSkillDeclaration(
                id=config.<AgentName>AgentConfig.SKILL_ID,
                name=config.<AgentName>AgentConfig.SKILL_NAME,
                description=config.<AgentName>AgentConfig.SKILL_DESCRIPTION,
            ),
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

        Every value the tool needs is a parameter of its own: AgentBase runs the agent without
        dependencies, so a tool can never read them from the run context.

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

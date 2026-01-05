# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from pydantic_ai.mcp import MCPServerSSE

import config
from common.agent_base import AgentBase, MCP_SERVER_ATTACHMENTS_FOLDER_PATH
from agents.requirements_review.prompt import RequirementsReviewSystemPrompt
from common import utils
from common.models import JiraUserStory, RequirementsReviewFeedback

logger = utils.get_logger("reviewer_agent")
jira_mcp_server = MCPServerSSE(url=config.JIRA_MCP_SERVER_URL, timeout=config.MCP_SERVER_TIMEOUT_SECONDS)


class RequirementsReviewAgent(AgentBase):
    def __init__(self):
        atlassian_mcp_server = jira_mcp_server
        instruction_prompt = RequirementsReviewSystemPrompt(
            attachments_remote_folder_path=MCP_SERVER_ATTACHMENTS_FOLDER_PATH
        )
        super().__init__(
            agent_name=config.RequirementsReviewAgentConfig.OWN_NAME,
            base_url=config.AGENT_BASE_URL,
            port=config.RequirementsReviewAgentConfig.PORT,
            external_port=config.RequirementsReviewAgentConfig.EXTERNAL_PORT,
            protocol=config.RequirementsReviewAgentConfig.PROTOCOL,
            model_name=config.RequirementsReviewAgentConfig.MODEL_NAME,
            output_type=RequirementsReviewFeedback,
            instructions=instruction_prompt.get_prompt(),
            mcp_servers=[atlassian_mcp_server],
            deps_type=JiraUserStory,
            description="Agent which does the review of requirements including Jira user stories",
            tools=[self._fetch_attachments]
        )

    def get_thinking_budget(self) -> int:
        return config.RequirementsReviewAgentConfig.THINKING_BUDGET

    def get_max_requests_per_task(self) -> int:
        return config.RequirementsReviewAgentConfig.MAX_REQUESTS_PER_TASK


agent = RequirementsReviewAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()

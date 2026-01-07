# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerSSE
from pydantic_ai.messages import BinaryContent

import config
from common.agent_base import AgentBase, MCP_SERVER_ATTACHMENTS_FOLDER_PATH
from agents.requirements_review.prompt import (
    RequirementsReviewSystemPrompt,
    RequirementsReviewWithAttachmentsPrompt
)
from common import utils
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import JiraUserStory, RequirementsReviewFeedback

logger = utils.get_logger("reviewer_agent")
jira_mcp_server = MCPServerSSE(url=config.JIRA_MCP_SERVER_URL, timeout=config.MCP_SERVER_TIMEOUT_SECONDS)


class RequirementsReviewAgent(AgentBase):
    def __init__(self):
        # Create a sub-agent for reviewing with attachments
        self.review_agent = Agent(
            model=CustomLlmWrapper(wrapped=config.RequirementsReviewAgentConfig.MODEL_NAME),
            output_type=RequirementsReviewFeedback,
            system_prompt=RequirementsReviewWithAttachmentsPrompt().get_prompt(),
            name="review_with_attachments",
        )

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
            mcp_servers=[jira_mcp_server],
            deps_type=JiraUserStory,
            description="Agent which does the review of requirements including Jira user stories",
            tools=[self._review_with_attachments]
        )

    def get_thinking_budget(self) -> int:
        return config.RequirementsReviewAgentConfig.THINKING_BUDGET

    def get_max_requests_per_task(self) -> int:
        return config.RequirementsReviewAgentConfig.MAX_REQUESTS_PER_TASK

    async def _review_with_attachments(self, jira_issue_content: str, attachment_paths: list[str]) -> RequirementsReviewFeedback:
        """
        Reviews a Jira issue, taking into account all its attachments.
        
        Args:
            jira_issue_content: The complete content of the Jira issue.
            attachment_paths: List of file paths to the downloaded attachments.
            
        Returns:
            Requirements review feedback with improvement suggestions.
        """

        attachments_content = self._fetch_attachments(attachment_paths)
        user_message_parts: list[str | BinaryContent] = [
            f"Jira Issue content:\n```{jira_issue_content}```"
        ]
        if attachments_content:
            for filename, binary_content in attachments_content.items():
                user_message_parts.append(f"Attachment: {filename}")
                user_message_parts.append(binary_content)
        logger.info("Starting requirements review with %d attachments", len(attachments_content))
        result = await self.review_agent.run(user_message_parts)
        feedback: RequirementsReviewFeedback = result.output
        logger.info(f"Generated improvement suggestions as a feedback")
        return feedback


agent = RequirementsReviewAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()

# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from typing import TYPE_CHECKING

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerSSE

import config
from agents.test_case_review.prompt import TestCaseReviewSystemPrompt, TestCaseReviewWithAttachmentsPrompt
from common import utils
from common.agent_base import MCP_SERVER_ATTACHMENTS_FOLDER_PATH, AgentBase
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import TestCase, TestCaseReviewFeedbacks, TestCaseReviewRequest
from common.services.test_management_system_client_provider import get_test_management_client

if TYPE_CHECKING:
    from pydantic_ai.messages import BinaryContent

logger = utils.get_logger("test_case_review_agent")
jira_mcp_server = MCPServerSSE(url=config.JIRA_MCP_SERVER_URL, timeout=config.MCP_SERVER_TIMEOUT_SECONDS)


class TestCaseReviewAgent(AgentBase):
    __test__ = False

    def __init__(self):
        # Create a sub-agent for reviewing with attachments
        self.review_agent = Agent(
            model=CustomLlmWrapper(wrapped=config.TestCaseReviewAgentConfig.MODEL_NAME),
            output_type=TestCaseReviewFeedbacks,
            system_prompt=TestCaseReviewWithAttachmentsPrompt().get_prompt(),
            name="review_test_cases_with_attachments",
        )

        instruction_prompt = TestCaseReviewSystemPrompt(
            attachments_remote_folder_path=MCP_SERVER_ATTACHMENTS_FOLDER_PATH
        )
        super().__init__(
            agent_name=config.TestCaseReviewAgentConfig.OWN_NAME,
            base_url=config.AGENT_BASE_URL,
            port=config.TestCaseReviewAgentConfig.PORT,
            external_port=config.TestCaseReviewAgentConfig.EXTERNAL_PORT,
            protocol=config.TestCaseReviewAgentConfig.PROTOCOL,
            model_name=config.TestCaseReviewAgentConfig.MODEL_NAME,
            deps_type=TestCaseReviewRequest,
            output_type=TestCaseReviewFeedbacks,
            instructions=instruction_prompt.get_prompt(),
            mcp_servers=[jira_mcp_server],
            description="Agent which reviews generated test cases for coherence, redundancy, and effectiveness.",
            tools=[self.add_review_feedback, self.set_test_case_status_to_review_complete, self._review_test_cases_with_attachments]
        )

    def get_thinking_budget(self) -> int:
        return config.TestCaseReviewAgentConfig.THINKING_BUDGET

    def get_max_requests_per_task(self) -> int:
        return config.TestCaseReviewAgentConfig.MAX_REQUESTS_PER_TASK

    async def _review_test_cases_with_attachments(self, jira_issue_content: str, attachment_paths: list[str],
                                                  test_cases: list[TestCase]) -> TestCaseReviewFeedbacks:
        """
        Reviews a list of test cases, taking into account the Jira issue content and its attachments.

        Args:
            jira_issue_content: The complete content of the Jira issue.
            attachment_paths: List of file paths to the downloaded attachments.
            test_cases: The list of test cases to review.

        Returns:
            Test case review feedbacks with improvement suggestions for each test case.
        """

        attachments_content = self._fetch_attachments(attachment_paths)
        test_cases_str = "\n".join([str(tc) for tc in test_cases])

        user_message_parts: list[str | BinaryContent] = [
            f"Jira Issue content:\n```{jira_issue_content}```",
            f"Test Cases to Review:\n```{test_cases_str}```"
        ]
        if attachments_content:
            for filename, binary_content in attachments_content.items():
                user_message_parts.append(f"Attachment: {filename}")
                user_message_parts.append(binary_content)

        logger.info(f"Starting review of {len(test_cases)} referring to the Jira issue content "
                    f"and {len(attachments_content) if attachments_content else 0} attachments.")
        result = await self.review_agent.run(user_message_parts)
        feedbacks: TestCaseReviewFeedbacks = result.output
        logger.info(f"Generated review feedbacks for {len(feedbacks.review_feedbacks)} test cases")
        return feedbacks

    @staticmethod
    def add_review_feedback(test_case_key: str, feedback: str) -> str:
        """
        Adds feedback as a comment to the test case.

        Args:
            test_case_key: The key or ID of the test case.
            feedback: Test case review feedback.

        Returns:
            A confirmation message informing if the feedback was successfully added.
        """
        client = get_test_management_client()
        client.add_test_case_review_comment(test_case_key, feedback)
        result_info = f"Successfully added the test case review feedback for the test case with key(ID) '{test_case_key}'"
        logger.info(result_info)
        return result_info

    @staticmethod
    def set_test_case_status_to_review_complete(project_key: str, test_case_key: str) -> str:
        """
        Sets the status of a test case to "Review Complete".

        Args:
            project_key: The key of the Jira project the test case belongs to.
            test_case_key: The key or ID of the test case.

        Returns:
            A confirmation message informing if the status was successfully updated.
        """
        client = get_test_management_client()
        client.change_test_case_status(project_key, test_case_key,
                                       config.TestCaseReviewAgentConfig.REVIEW_COMPLETE_STATUS_NAME)
        result_info = f"Successfully set status of test case '{test_case_key}' to '{config.TestCaseReviewAgentConfig.REVIEW_COMPLETE_STATUS_NAME}'"
        logger.info(result_info)
        return result_info


agent = TestCaseReviewAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from typing import TYPE_CHECKING

from pydantic_ai.settings import ThinkingLevel
from pydantic_ai.tools import Tool
from pydantic_ai.usage import RunUsage, UsageLimits

import config
from agents.test_case_review.prompt import TestCaseReviewSystemPrompt, TestCaseReviewWithAttachmentsPrompt
from common import utils
from common.agent_base import MCP_SERVER_ATTACHMENTS_FOLDER_PATH, AgentBase
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import TestCase, TestCaseReviewFeedback, TestCaseReviewFeedbacks, TestCaseReviewRequest
from common.services.jira_mcp import build_jira_mcp_server_toolset
from common.services.test_management_system_client_provider import get_test_management_client

if TYPE_CHECKING:
    from pydantic_ai.messages import BinaryContent

logger = utils.get_logger("test_case_review_agent")


class TestCaseReviewAgent(AgentBase):
    __test__ = False

    def __init__(self):
        # Create a sub-agent for reviewing with attachments
        self.review_agent = CustomLlmWrapper.create_agent(
            model_name=config.TestCaseReviewAgentConfig.MODEL_NAME,
            output_type=TestCaseReviewFeedback,
            system_prompt=TestCaseReviewWithAttachmentsPrompt().get_prompt(),
            name="review_test_cases_with_attachments",
            thinking_level=config.TestCaseReviewAgentConfig.THINKING_LEVEL,
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
            version=config.TestCaseReviewAgentConfig.VERSION,
            deps_type=TestCaseReviewRequest,
            output_type=TestCaseReviewFeedbacks,
            instructions=instruction_prompt.get_prompt(),
            mcp_toolset_factories=[build_jira_mcp_server_toolset],
            description="Agent which reviews generated test cases for coherence, redundancy, and effectiveness.",
            tools=[
                # These two tools both do a full read-modify-write PUT on the same Jira/Zephyr
                # test case. Marking them sequential forces pydantic-ai to run the whole turn one
                # call at a time, so the status update and the comment update can't race and
                # clobber each other's field (last-writer-wins).
                Tool(self.add_review_feedback, sequential=True),
                Tool(self.set_test_case_status_to_review_complete, sequential=True),
                self._review_test_cases_with_attachments,
            ],
        )

    def get_thinking_level(self) -> ThinkingLevel:
        return config.TestCaseReviewAgentConfig.THINKING_LEVEL

    def get_max_requests_per_task(self) -> int:
        return config.TestCaseReviewAgentConfig.MAX_REQUESTS_PER_TASK

    async def _review_test_cases_with_attachments(
        self, jira_issue_content: str, attachment_paths: list[str], test_cases: list[TestCase]
    ) -> TestCaseReviewFeedbacks:
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
        attachment_parts: list[str | BinaryContent] = []
        for filename, binary_content in (attachments_content or {}).items():
            attachment_parts.append(f"Attachment: {filename}")
            attachment_parts.append(binary_content)

        logger.info(
            f"Starting review of {len(test_cases)} test case(s) referring to the Jira issue content "
            f"and {len(attachment_parts) // 2} attachments."
        )

        # One sub-agent run per test case keeps the model focused on a single review target, while the
        # remaining test cases stay in the context so duplicate coverage can still be detected.
        # The sub-agent runs are separate from the main agent run and therefore outside its budget.
        # One shared usage object keeps the whole loop inside the per-task token cap.
        review_usage = RunUsage()
        review_usage_limits = UsageLimits(total_tokens_limit=config.BudgetConfig.TOTAL_TOKENS_LIMIT_PER_TASK)

        feedbacks: list[TestCaseReviewFeedback] = []
        for index, test_case in enumerate(test_cases, start=1):
            other_test_cases = "\n".join(str(other) for other in test_cases if other is not test_case)
            user_message_parts: list[str | BinaryContent] = [
                f"Jira Issue content:\n```{jira_issue_content}```",
                f"Test Case under review:\n```{test_case!s}```",
                f"Other test cases created for the same Jira issue (context only):\n```{other_test_cases}```",
                *attachment_parts,
            ]
            logger.info(f"Reviewing test case {index}/{len(test_cases)}")
            result = await self.review_agent.run(
                user_message_parts, usage=review_usage, usage_limits=review_usage_limits
            )
            if result.output.llm_comments:
                logger.warning(
                    f"Review of test case '{result.output.test_case_id}' reported: {result.output.llm_comments}"
                )
            feedbacks.append(result.output)

        logger.info(f"Generated review feedbacks for {len(feedbacks)} test cases")
        return TestCaseReviewFeedbacks(review_feedbacks=feedbacks)

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
        result_info = (
            f"Successfully added the test case review feedback for the test case with key(ID) '{test_case_key}'"
        )
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
        client.change_test_case_status(
            project_key, test_case_key, config.TestCaseReviewAgentConfig.REVIEW_COMPLETE_STATUS_NAME
        )
        result_info = f"Successfully set status of test case '{test_case_key}' to '{config.TestCaseReviewAgentConfig.REVIEW_COMPLETE_STATUS_NAME}'"
        logger.info(result_info)
        return result_info


agent = TestCaseReviewAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
import html
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, override

from a2a.types import Message
from pydantic_ai import ModelRetry
from pydantic_ai.settings import ThinkingLevel
from pydantic_ai.tools import Tool
from pydantic_ai.usage import RunUsage, UsageLimits
from qdrant_client import models as qdrant_models

import config
from agents.test_case_review.prompt import (
    TestCaseDuplicateJudgePrompt,
    TestCaseReviewSystemPrompt,
    TestCaseReviewWithAttachmentsPrompt,
)
from common import utils
from common.agent_base import AgentBase
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import (
    AgentSkillDeclaration,
    ListedTestCase,
    OverlappingTestCase,
    TestCase,
    TestCaseDuplicateCheck,
    TestCaseDuplicateJudgement,
    TestCaseReviewFeedback,
    TestCaseReviewFeedbacks,
)
from common.services.atlassian_mcp import build_atlassian_mcp_server_toolset
from common.services.test_case_index import IndexedTestCase, render_test_case
from common.services.test_management_system_client_provider import get_test_management_client

if TYPE_CHECKING:
    from pydantic_ai.messages import BinaryContent

logger = utils.get_logger("test_case_review_agent")

# The Jira tools this agent actually uses (WS11 per-agent tool filtering): it reads the
# issue; attachments arrive through the REST downloader and every write goes to the test
# management system.
_JIRA_TOOL_ALLOWLIST = ("jira_get_issue",)

DUPLICATE_CHECK_HEADING = "Duplicate check"

# The duplicate-check verdicts of the review task running in this context, keyed by test case key.
# Set per run, so concurrent review tasks served by the same agent instance never see each other's verdicts.
_duplicate_checks: ContextVar[dict[str, TestCaseDuplicateCheck] | None] = ContextVar(
    "test_case_duplicate_checks", default=None
)


class TestCaseDuplicateCheckError(RuntimeError):
    """Raised when the duplicate check cannot run; it aborts the review instead of reporting no duplicates."""

    __test__ = False


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
            max_output_tokens=config.TestCaseReviewAgentConfig.MAX_OUTPUT_TOKENS,
        )
        self.duplicate_judge = CustomLlmWrapper.create_agent(
            model_name=config.TestCaseReviewAgentConfig.MODEL_NAME,
            output_type=TestCaseDuplicateJudgement,
            system_prompt=TestCaseDuplicateJudgePrompt().get_prompt(),
            name="test_case_duplicate_judge",
            thinking_level=config.TestCaseReviewAgentConfig.THINKING_LEVEL,
            max_output_tokens=config.TestCaseReviewAgentConfig.MAX_OUTPUT_TOKENS,
        )

        instruction_prompt = TestCaseReviewSystemPrompt()
        super().__init__(
            agent_name=config.TestCaseReviewAgentConfig.OWN_NAME,
            base_url=config.AGENT_BASE_URL,
            port=config.TestCaseReviewAgentConfig.PORT,
            external_port=config.TestCaseReviewAgentConfig.EXTERNAL_PORT,
            protocol=config.TestCaseReviewAgentConfig.PROTOCOL,
            model_name=config.TestCaseReviewAgentConfig.MODEL_NAME,
            version=config.TestCaseReviewAgentConfig.VERSION,
            max_output_tokens=config.TestCaseReviewAgentConfig.MAX_OUTPUT_TOKENS,
            output_type=TestCaseReviewFeedbacks,
            instructions=instruction_prompt.get_prompt(),
            mcp_toolset_factories=[lambda: build_atlassian_mcp_server_toolset(_JIRA_TOOL_ALLOWLIST)],
            skill=AgentSkillDeclaration(
                id=config.TestCaseReviewAgentConfig.SKILL_ID,
                name=config.TestCaseReviewAgentConfig.SKILL_NAME,
                description=config.TestCaseReviewAgentConfig.SKILL_DESCRIPTION,
            ),
            tools=[
                # These two tools both do a full read-modify-write PUT on the same Jira/Zephyr
                # test case. Marking them sequential forces pydantic-ai to run the whole turn one
                # call at a time, so the status update and the comment update can't race and
                # clobber each other's field (last-writer-wins).
                Tool(self.add_review_feedback, sequential=True),
                Tool(self.set_test_case_status_to_review_complete, sequential=True),
                self._review_test_cases_with_attachments,
            ],
            vector_db_collection_name=config.QdrantConfig.TEST_CASES_COLLECTION_NAME,
        )
        # The verdicts reach the returned feedback deterministically, whatever the model wrote.
        self.agent.output_validator(_attach_duplicate_checks)

    def get_thinking_level(self) -> ThinkingLevel:
        return config.TestCaseReviewAgentConfig.THINKING_LEVEL

    def get_max_requests_per_task(self) -> int:
        return config.TestCaseReviewAgentConfig.MAX_REQUESTS_PER_TASK

    @override
    async def run(self, received_message: Message) -> Message:
        token = _duplicate_checks.set({})
        try:
            return await super().run(received_message)
        finally:
            _duplicate_checks.reset(token)

    async def _review_test_cases_with_attachments(
        self,
        project_key: str,
        jira_issue_key: str,
        jira_issue_content: str,
        test_cases: list[TestCase],
    ) -> TestCaseReviewFeedbacks:
        """
        Reviews a list of test cases, taking into account the Jira issue content and its attachments,
        and checks every test case for duplicates among the existing test cases of the project.

        Args:
            project_key: The key of the Jira project the test cases belong to.
            jira_issue_key: The key of the Jira issue (e.g. PROJ-123), used to download its attachments.
            jira_issue_content: The complete content of the Jira issue.
            test_cases: The list of test cases to review.

        Returns:
            Test case review feedbacks with improvement suggestions and the duplicate check for each test case.
        """

        from common.services.jira_attachments import download_issue_attachments

        if not project_key.strip():
            raise ValueError("project_key must not be blank for the test case review.")
        checks = _current_duplicate_checks()
        records = await self._index_review_batch(project_key, test_cases)

        attachments_content = download_issue_attachments(jira_issue_key)
        attachment_parts: list[str | BinaryContent] = []
        for filename, binary_content in (attachments_content or {}).items():
            attachment_parts.append(f"Attachment: {filename}")
            attachment_parts.append(binary_content)

        logger.info(
            "Starting review of %s test case(s) referring to the Jira issue content and %s attachments.",
            len(test_cases),
            len(attachment_parts) // 2,
        )

        # One sub-agent run per test case keeps the model focused on a single review target, while the
        # remaining test cases stay in the context so duplicate coverage can still be detected.
        # The sub-agent runs are separate from the main agent run and therefore outside its budget.
        # One shared usage object keeps the whole loop inside the per-task token cap.
        review_usage = RunUsage()
        review_usage_limits = UsageLimits(total_tokens_limit=config.BudgetConfig.TOTAL_TOKENS_LIMIT_PER_TASK)

        feedbacks: list[TestCaseReviewFeedback] = []
        for index, (test_case, record) in enumerate(zip(test_cases, records, strict=True), start=1):
            other_test_cases = "\n".join(str(other) for other in test_cases if other is not test_case)
            user_message_parts: list[str | BinaryContent] = [
                f"Jira Issue content:\n```{jira_issue_content}```",
                f"Test Case under review:\n```{test_case!s}```",
                f"Other test cases created for the same Jira issue (context only):\n```{other_test_cases}```",
                *attachment_parts,
            ]
            logger.info("Reviewing test case %s/%s", index, len(test_cases))
            result = await self.review_agent.run(
                user_message_parts, usage=review_usage, usage_limits=review_usage_limits
            )
            if result.output.llm_comments:
                logger.warning(
                    "Review of test case '%s' reported: %s", result.output.test_case_id, result.output.llm_comments
                )
            duplicate_check = await self._check_duplicates(project_key, record, review_usage, review_usage_limits)
            checks[record.test_case_key] = duplicate_check
            result.output.duplicate_check = duplicate_check
            feedbacks.append(result.output)

        logger.info("Generated review feedbacks for %s test cases", len(feedbacks))
        return TestCaseReviewFeedbacks(review_feedbacks=feedbacks)

    async def _index_review_batch(self, project_key: str, test_cases: list[TestCase]) -> list[IndexedTestCase]:
        """Indexes the batch under review, so the duplicate search sees test cases created minutes earlier."""
        keys = [test_case.key or "" for test_case in test_cases]
        if not all(keys):
            raise ValueError(f"Every test case under review needs a key for the duplicate check; got {keys}.")
        # The review ends by setting this status; the next test-case sync records the actual one.
        status = config.TestCaseReviewAgentConfig.REVIEW_COMPLETE_STATUS_NAME
        records = [
            render_test_case(project_key, ListedTestCase(test_case=test_case, status=status))
            for test_case in test_cases
        ]
        with _fail_loudly("indexing", project_key, keys):
            await self.vector_db_service.upsert_batch(records)
        logger.info("Indexed %d test case(s) under review for project %s.", len(records), project_key)
        return records

    async def _check_duplicates(
        self, project_key: str, record: IndexedTestCase, usage: RunUsage, usage_limits: UsageLimits
    ) -> TestCaseDuplicateCheck:
        """Finds the existing test cases of the project whose coverage overlaps the reviewed one."""
        test_case_key = record.test_case_key
        with _fail_loudly("search", project_key, [test_case_key]):
            hits = await self.vector_db_service.hybrid_search(
                record.text,
                limit=config.QdrantConfig.TEST_CASE_DUPLICATE_MAX_CANDIDATES,
                score_threshold=config.QdrantConfig.TEST_CASE_DUPLICATE_MIN_SCORE,
                query_filter=_duplicate_candidates_filter(project_key, test_case_key),
            )
        candidates = _unique_candidates(hits, test_case_key)
        if not candidates:
            logger.info("No duplicate candidates found for test case %s of project %s.", test_case_key, project_key)
            return TestCaseDuplicateCheck()

        logger.info("Judging %d duplicate candidate(s) for test case %s.", len(candidates), test_case_key)
        with _fail_loudly("judgement", project_key, [test_case_key]):
            result = await self.duplicate_judge.run(
                _judge_message(record, candidates), usage=usage, usage_limits=usage_limits
            )
        return _validated_check(test_case_key, result.output, candidates)

    @staticmethod
    async def add_review_feedback(test_case_key: str, feedback: str) -> str:
        """
        Adds feedback as a comment to the test case. The duplicate check of the test case is appended to the
        comment automatically.

        Args:
            test_case_key: The key or ID of the test case.
            feedback: Test case review feedback.

        Returns:
            A confirmation message informing if the feedback was successfully added.
        """
        duplicate_check = _current_duplicate_checks().get(test_case_key)
        if duplicate_check is None:
            raise ModelRetry(
                f"No duplicate check exists for the test case '{test_case_key}'. Review the test case with the "
                "review tool first and pass exactly the key of a reviewed test case."
            )
        comment = f"{feedback}\n{render_duplicate_check(duplicate_check)}"
        client = get_test_management_client()
        await asyncio.to_thread(client.add_test_case_review_comment, test_case_key, comment)
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


def render_duplicate_check(duplicate_check: TestCaseDuplicateCheck) -> str:
    """Renders the duplicate check as the HTML section appended to the test case's review comment."""
    heading = f"<h4>{DUPLICATE_CHECK_HEADING}</h4>"
    if not duplicate_check.overlapping_test_cases:
        return f"{heading}<p>No duplicate test cases found.</p>"
    items = "".join(
        f"<li><b>{html.escape(overlap.test_case_key)}</b>: {html.escape(overlap.overlap_explanation)}</li>"
        for overlap in duplicate_check.overlapping_test_cases
    )
    return f"{heading}<p>This test case overlaps in coverage with:</p><ul>{items}</ul>"


def _current_duplicate_checks() -> dict[str, TestCaseDuplicateCheck]:
    """The verdict store of the running review task."""
    checks = _duplicate_checks.get()
    if checks is None:
        raise RuntimeError("The duplicate-check store is only available inside a review task run.")
    return checks


def _attach_duplicate_checks(output: TestCaseReviewFeedbacks) -> TestCaseReviewFeedbacks:
    """Copies the verdicts computed in code onto the final output of the main agent."""
    checks = _duplicate_checks.get() or {}
    for feedback in output.review_feedbacks:
        feedback.duplicate_check = checks.get(feedback.test_case_id)
    return output


@contextmanager
def _fail_loudly(stage: str, project_key: str, test_case_keys: Sequence[str]) -> Iterator[None]:
    """Aborts the review when a duplicate-check stage fails, so nobody reads 'no duplicates' for a check never run."""
    try:
        yield
    except Exception as exc:
        keys = ", ".join(test_case_keys)
        logger.error(
            "Duplicate check %s failed for test case(s) %s of project %s; aborting the review.",
            stage,
            keys,
            project_key,
        )
        raise TestCaseDuplicateCheckError(
            f"Duplicate check {stage} failed for test case(s) {keys} of project {project_key}: {exc}"
        ) from exc


def _duplicate_candidates_filter(project_key: str, test_case_key: str) -> qdrant_models.Filter:
    """Test cases of the same project, excluding the reviewed test case itself."""
    return qdrant_models.Filter(
        must=[
            qdrant_models.FieldCondition(key="source", match=qdrant_models.MatchValue(value="test_case")),
            qdrant_models.FieldCondition(key="project_key", match=qdrant_models.MatchValue(value=project_key)),
        ],
        must_not=[
            qdrant_models.FieldCondition(key="test_case_key", match=qdrant_models.MatchValue(value=test_case_key)),
        ],
    )


def _unique_candidates(hits: list[qdrant_models.ScoredPoint], own_key: str) -> dict[str, str]:
    """The candidates' texts by test case key, one per key, never the reviewed test case itself."""
    candidates: dict[str, str] = {}
    for hit in hits:
        payload = hit.payload or {}
        key = payload.get("test_case_key")
        if key and key != own_key and key not in candidates:
            candidates[key] = payload.get("text", "")
    return candidates


def _judge_message(record: IndexedTestCase, candidates: dict[str, str]) -> str:
    """The judge's input: the reviewed test case and the candidates keyed by their test case key."""
    candidate_blocks = "\n\n".join(f"Candidate {key}:\n```\n{text}\n```" for key, text in candidates.items())
    return f"Test case under review ({record.test_case_key}):\n```\n{record.text}\n```\n\n{candidate_blocks}"


def _validated_check(
    test_case_key: str, judgement: TestCaseDuplicateJudgement, candidates: dict[str, str]
) -> TestCaseDuplicateCheck:
    """Keeps only verdicts about actual candidates: the judge's output is untrusted."""
    overlapping: list[OverlappingTestCase] = []
    for overlap in judgement.overlapping_test_cases:
        if overlap.test_case_key in candidates:
            overlapping.append(overlap)
        else:
            logger.warning(
                "Duplicate judge named %s, which is no candidate of test case %s; ignoring it.",
                overlap.test_case_key,
                test_case_key,
            )
    return TestCaseDuplicateCheck(overlapping_test_cases=overlapping)


agent = TestCaseReviewAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()

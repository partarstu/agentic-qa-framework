# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.settings import ThinkingLevel
from pydantic_ai.tools import Tool
from pydantic_ai.usage import RunUsage, UsageLimits
from qdrant_client import models as qdrant_models

import config
from agents.test_case_review.prompt import (
    TestCaseDuplicateJudgePrompt,
    TestCaseReviewSystemPrompt,
    TestCaseReviewWithAttachmentsPrompt,
    TestSuiteReviewPrompt,
)
from common import utils
from common.agent_base import AgentBase, is_delegated_run
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import (
    AgentSkillDeclaration,
    FindingAction,
    OverlappingTestCase,
    ReviewFinding,
    TestCaseDesignSession,
    TestCaseDuplicateCheck,
    TestCaseDuplicateJudgement,
    TestCaseReviewFeedback,
    TestCaseReviewFeedbacks,
    TestSuiteReview,
)
from common.services.atlassian_mcp import build_atlassian_mcp_server_toolset
from common.services.atlassian_tools import JIRA_GET_ISSUE
from common.services.jira_attachments import attachment_parts, fetch_session_attachments
from common.services.test_case_index import IndexedTestCase, render_test_case
from common.services.test_management_tools import (
    add_review_feedback,
    hide_while_designing,
    set_test_case_status_to_review_complete,
)

if TYPE_CHECKING:
    from pydantic_ai.messages import BinaryContent

logger = utils.get_logger("test_case_review_agent")

# Attachments arrive through the REST downloader and every write goes to the test management system.
_JIRA_TOOL_ALLOWLIST = (JIRA_GET_ISSUE,)
# A single test case's review never sees the other test cases, so these actions are left to the whole-set review.
_WHOLE_SET_ACTIONS = frozenset({FindingAction.ADD_TEST_CASE, FindingAction.REMOVE_DUPLICATE_STEPS})


class TestCaseDuplicateCheckError(RuntimeError):
    """Raised when the duplicate check cannot run; it aborts the review instead of reporting no duplicates."""

    __test__ = False


class TestCaseReviewAgent(AgentBase):
    __test__ = False

    def __init__(self):
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
        self.test_suite_reviewer = CustomLlmWrapper.create_agent(
            model_name=config.TestCaseReviewAgentConfig.MODEL_NAME,
            output_type=TestSuiteReview,
            system_prompt=TestSuiteReviewPrompt().get_prompt(),
            name="test_suite_reviewer",
            deps_type=TestCaseDesignSession,
            thinking_level=config.TestCaseReviewAgentConfig.THINKING_LEVEL,
            max_output_tokens=config.TestCaseReviewAgentConfig.MAX_OUTPUT_TOKENS,
        )
        self.test_suite_reviewer.output_validator(_validate_test_suite_review)
        self.designing_instructions = TestCaseReviewSystemPrompt("designing_instructions.md").get_prompt()
        self.standalone_instructions = TestCaseReviewSystemPrompt("standalone_instructions.md").get_prompt()

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
            deps_type=TestCaseDesignSession,
            skill=AgentSkillDeclaration(
                id=config.TestCaseReviewAgentConfig.SKILL_ID,
                name=config.TestCaseReviewAgentConfig.SKILL_NAME,
                description=config.TestCaseReviewAgentConfig.SKILL_DESCRIPTION,
            ),
            tools=[
                # The feedback and status tools both do a full read-modify-write PUT on the same Jira/Zephyr
                # test case. Marking them sequential forces pydantic-ai to run the whole turn one
                # call at a time, so the status update and the comment update can't race and
                # clobber each other's field (last-writer-wins).
                Tool(add_review_feedback, sequential=True, prepare=hide_while_designing),
                Tool(set_test_case_status_to_review_complete, sequential=True, prepare=hide_while_designing),
                Tool(self.check_duplicates, prepare=hide_while_designing),
                self.review_test_cases,
                self.review_test_suite,
            ],
            vector_db_collection_name=config.QdrantConfig.TEST_CASES_COLLECTION_NAME,
        )
        self.agent.instructions(self._get_mode_instructions)

    def get_thinking_level(self) -> ThinkingLevel:
        return config.TestCaseReviewAgentConfig.THINKING_LEVEL

    def get_max_requests_per_task(self) -> int:
        return config.TestCaseReviewAgentConfig.MAX_REQUESTS_PER_TASK

    def _get_mode_instructions(self, ctx: RunContext[TestCaseDesignSession]) -> str:
        if ctx.deps is None:
            raise ValueError("A test case review needs the test case design session as its structured data part.")
        return self.designing_instructions if is_delegated_run() else self.standalone_instructions

    async def review_test_cases(
        self, ctx: RunContext[TestCaseDesignSession], jira_issue_content: str | None = None
    ) -> TestCaseReviewFeedbacks:
        """
        Reviews the test cases against the Jira issue content and its attachments. While designing, only the new and
        changed test cases are reviewed.

        Args:
            jira_issue_content: The complete content of the Jira issue; needed only when the test cases are saved
                ones, never while designing.

        Returns:
            The findings of each reviewed test case.
        """
        session = ctx.deps
        if session.story_content is None:
            if not jira_issue_content:
                raise ModelRetry("Pass the complete content of the Jira issue: the design holds none yet.")
            session.story_content = jira_issue_content
        designing = is_delegated_run()
        test_case_ids = [
            test_case_id
            for test_case_id in session.test_cases
            if test_case_id in session.changed_test_case_ids or not designing
        ]
        story_attachment_parts = attachment_parts(await fetch_session_attachments(session))
        logger.info(
            "Starting review of %s test case(s) referring to the Jira issue content and %s attachments.",
            len(test_case_ids),
            len(story_attachment_parts) // 2,
        )

        # One sub-agent run per test case keeps the model focused on a single review target; its relation to the other
        # test cases (coverage, duplicates) is the whole-set review's, so they are left out.
        usage_limits = self.get_sub_agent_usage_limits()
        feedbacks: list[TestCaseReviewFeedback] = []
        for index, test_case_id in enumerate(test_case_ids, start=1):
            test_case = session.test_cases[test_case_id]
            user_message_parts: list[str | BinaryContent] = [
                f"Jira Issue content:\n```{session.story_content}```",
                f"Test Case under review (ID {test_case_id}):\n```{test_case!s}```",
                *story_attachment_parts,
            ]
            logger.info("Reviewing test case %s/%s", index, len(test_case_ids))
            result = await self.review_agent.run(user_message_parts, usage=ctx.usage, usage_limits=usage_limits)
            if result.output.llm_comments:
                logger.warning("Review of test case '%s' reported: %s", test_case_id, result.output.llm_comments)
            findings = _owned_by(test_case_id, result.output.findings)
            session.findings[test_case_id] = findings
            feedbacks.append(TestCaseReviewFeedback(test_case_id=test_case_id, findings=findings))

        session.changed_test_case_ids.clear()
        logger.info("Generated review feedbacks for %s test cases", len(feedbacks))
        return TestCaseReviewFeedbacks(review_feedbacks=feedbacks)

    async def review_test_suite(self, ctx: RunContext[TestCaseDesignSession]) -> TestSuiteReview:
        """
        Reviews the whole set of test cases for coverage gaps of the Jira issue and for duplicate coverage inside the
        set, taking the findings of the individual reviews into account.

        Returns:
            The findings about the whole set, each assigned to the one test case whose change resolves it.
        """
        session = ctx.deps
        unreviewed = [test_case_id for test_case_id in session.test_cases if test_case_id not in session.findings]
        if session.story_content is None or unreviewed or session.changed_test_case_ids:
            raise ModelRetry("Review the new and changed test cases with the review tool first.")
        test_case_blocks = "\n\n".join(
            f"ID {test_case_id}:\n```{test_case!s}```\n"
            f"Findings of its individual review:\n```{_json_list(session.findings[test_case_id])}```"
            for test_case_id, test_case in session.test_cases.items()
        )
        user_message_parts: list[str | BinaryContent] = [
            f"Jira Issue content:\n```{session.story_content}```",
            f"Test cases:\n{test_case_blocks}",
            *attachment_parts(await fetch_session_attachments(session)),
        ]
        logger.info("Reviewing the whole set of %d test case(s).", len(session.test_cases))
        result = await self.test_suite_reviewer.run(
            user_message_parts, deps=session, usage=ctx.usage, usage_limits=self.get_sub_agent_usage_limits()
        )
        session.suite_findings = result.output.findings
        session.suite_reviewed = True
        logger.info("The whole-set review reported %d finding(s).", len(result.output.findings))
        return result.output

    async def check_duplicates(self, ctx: RunContext[TestCaseDesignSession]) -> str:
        """
        Checks the content of every reviewed test case for duplicates among the existing test cases of the project.

        Returns:
            The keys of the existing test cases each test case overlaps with.
        """
        session = ctx.deps
        if session.duplicate_checks:
            raise ModelRetry("The test cases are already checked for duplicates; never check them twice.")
        unreviewed = [test_case_id for test_case_id in session.test_cases if test_case_id not in session.findings]
        if not session.test_cases or unreviewed or session.changed_test_case_ids:
            raise ModelRetry("Review the test cases first; only reviewed test cases are checked for duplicates.")
        usage_limits = self.get_sub_agent_usage_limits()
        for test_case_id, test_case in session.test_cases.items():
            record = render_test_case(session.project_key, test_case.model_copy(update={"key": test_case_id}))
            session.duplicate_checks[test_case_id] = await self._check_duplicates(
                session.project_key, record, ctx.usage, usage_limits
            )
        overlaps = {
            test_case_id: [overlap.test_case_key for overlap in check.overlapping_test_cases]
            for test_case_id, check in session.duplicate_checks.items()
        }
        return "\n".join(
            f"{test_case_id}: {', '.join(keys) or 'no duplicates'}" for test_case_id, keys in overlaps.items()
        )

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


def _finding_errors(finding: ReviewFinding, known_ids: set[str]) -> list[str]:
    """What makes a finding unusable: an owner that contradicts its action, or an ID of no known test case."""
    owner = finding.owner_test_case_id
    errors: list[str] = []
    if finding.action is FindingAction.ADD_TEST_CASE and owner is not None:
        errors.append(f"An '{finding.action}' finding has no owner test case, but '{owner}' was given.")
    if finding.action is not FindingAction.ADD_TEST_CASE and owner is None:
        errors.append(f"A '{finding.action}' finding needs exactly one owner test case: '{finding.description}'.")
    unknown = [
        test_case_id
        for test_case_id in (owner, *finding.related_test_case_ids)
        if test_case_id is not None and test_case_id not in known_ids
    ]
    if unknown:
        errors.append(f"Unknown test case IDs {unknown}; use only these: {sorted(known_ids)}.")
    return errors


def _validate_test_suite_review(ctx: RunContext[TestCaseDesignSession], output: TestSuiteReview) -> TestSuiteReview:
    known_ids = set(ctx.deps.test_cases)
    errors = [error for finding in output.findings for error in _finding_errors(finding, known_ids)]
    if errors:
        raise ModelRetry("\n".join(errors))
    return output


def _owned_by(test_case_id: str, findings: Iterable[ReviewFinding]) -> list[ReviewFinding]:
    """The findings of a single test case's review, all owned by it; coverage and duplicates are the whole-set review's."""
    owned: list[ReviewFinding] = []
    for finding in findings:
        if finding.action in _WHOLE_SET_ACTIONS:
            logger.warning("Dropping the whole-set finding reported by the review of %s: %s", test_case_id, finding)
            continue
        owned.append(finding.model_copy(update={"owner_test_case_id": test_case_id, "related_test_case_ids": []}))
    return owned


def _json_list(findings: list[ReviewFinding]) -> str:
    return "[" + ", ".join(finding.model_dump_json() for finding in findings) + "]"


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

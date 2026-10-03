# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any, override

from fastapi import FastAPI
from pydantic import BaseModel
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.settings import ThinkingLevel
from pydantic_ai.tools import Tool, ToolDefinition
from pydantic_ai.toolsets import ToolsetTool, WrapperToolset
from pydantic_ai.usage import RunUsage

import config
from agents.test_case_classification import main as classification_main
from agents.test_case_design.prompt import TestCaseDesignSystemPrompt
from agents.test_case_generation.main import TestCaseGenerator
from agents.test_case_review.main import TestCaseDuplicateCheckError, TestCaseReviewer
from common import utils
from common.agent_base import AgentBase
from common.jira_additional_fields import build_additional_fields_instruction
from common.models import (
    AgentSkillDeclaration,
    DesignStopReason,
    TestCaseDesignRequest,
    TestCaseDesignResult,
    TestCaseDesignSession,
    TestCaseKeys,
    TestCaseReviewFindingAction,
    TestCaseReviewFindingSeverity,
)
from common.services.atlassian_mcp import build_atlassian_mcp_server_toolset
from common.services.atlassian_tools import JIRA_GET_ISSUE
from common.services.test_management_tools import (
    add_review_feedback,
    set_test_case_status_to_review_complete,
    upload_test_cases,
)

logger = utils.get_logger("test_case_design_agent")


class _JiraIssue(BaseModel):
    id: int


class DesignAbortedError(Exception):
    """Raised when the model gives up on the design after an unrecoverable error; it fails the task without retries."""


class TestCaseDesignAgent(AgentBase):
    __test__ = False

    def __init__(self) -> None:
        self.generator = TestCaseGenerator()
        self.reviewer = TestCaseReviewer()
        self.classification_agent = classification_main.agent
        self.max_iterations = config.TestCaseDesignAgentConfig.MAX_ITERATIONS
        self.fix_min_severity = TestCaseReviewFindingSeverity(config.TestCaseDesignAgentConfig.FIX_MIN_SEVERITY)
        super().__init__(
            agent_name=config.TestCaseDesignAgentConfig.OWN_NAME,
            base_url=config.AGENT_BASE_URL,
            port=config.TestCaseDesignAgentConfig.PORT,
            external_port=config.TestCaseDesignAgentConfig.EXTERNAL_PORT,
            protocol=config.TestCaseDesignAgentConfig.PROTOCOL,
            model_name=config.TestCaseDesignAgentConfig.MODEL_NAME,
            version=config.TestCaseDesignAgentConfig.VERSION,
            max_output_tokens=config.TestCaseDesignAgentConfig.MAX_OUTPUT_TOKENS,
            output_type=TestCaseDesignResult,
            instructions=TestCaseDesignSystemPrompt().get_prompt(),
            deps_type=TestCaseDesignSession,
            mcp_toolset_factories=[
                lambda: _StoryFetchingToolset(build_atlassian_mcp_server_toolset((JIRA_GET_ISSUE,)))
            ],
            skill=AgentSkillDeclaration(
                id=config.TestCaseDesignAgentConfig.SKILL_ID,
                name=config.TestCaseDesignAgentConfig.SKILL_NAME,
                description=config.TestCaseDesignAgentConfig.SKILL_DESCRIPTION,
            ),
            # Each tool checks the session before its first await and updates it after, so two calls of one model
            # response must not overlap: the second one then finds the step done.
            tools=[
                Tool(self.generate_test_cases, sequential=True),
                Tool(self.review_test_cases, sequential=True),
                Tool(self.fix_test_cases, sequential=True, prepare=_hide_outside_fix_loop),
                Tool(self.publish_test_cases, sequential=True, prepare=_hide_until_stopped),
            ],
        )
        self.agent.instructions(_story_instructions)
        self.agent.output_validator(_complete_result)

    def get_thinking_level(self) -> ThinkingLevel:
        return config.TestCaseDesignAgentConfig.THINKING_LEVEL

    def get_max_requests_per_task(self) -> int:
        return config.TestCaseDesignAgentConfig.MAX_REQUESTS_PER_TASK

    def get_total_tokens_limit(self) -> int:
        return config.TestCaseDesignAgentConfig.TOTAL_TOKENS_LIMIT

    @override
    def get_request_limit(self) -> int | None:
        # The delegated runs share the design's cumulative usage, which pydantic-ai's default request cap would cut
        # short; the tool-call and token budgets bound the design instead.
        return None

    @override
    def _build_deps(self, data: object) -> TestCaseDesignSession:
        """Starts a new design session from the request, the only state a caller may pass."""
        return TestCaseDesignSession(story_key=TestCaseDesignRequest.model_validate(data).story_key)

    @override
    @asynccontextmanager
    async def _lifespan(self, app: FastAPI) -> AsyncIterator[None]:
        async with super()._lifespan(app):
            yield
        # The reviewer runs in-process without a server, so no lifespan of its own closes its vector DB client.
        await self.reviewer.close()

    async def generate_test_cases(self, ctx: RunContext[TestCaseDesignSession]) -> str:
        """
        Generates the test cases of the fetched user story as drafts of the design.

        Returns:
            The extracted acceptance criteria, the generated test cases with the acceptance criteria each verifies, and
            the acceptance criteria left without a test case.
        """
        session = ctx.deps
        if session.test_cases:
            raise ModelRetry("The test cases are already generated; review them next.")
        if session.story_content is None:
            raise ModelRetry(f"Fetch the user story {session.story_key} first.")
        summary = await self.generator.generate(session, ctx.usage, self.get_sub_agent_usage_limits())
        logger.info("Generated %d test case(s) of %s.", len(session.test_cases), session.story_key)
        return summary

    async def review_test_cases(self, ctx: RunContext[TestCaseDesignSession]) -> str:
        """
        Reviews the new and changed test cases and the whole set, and decides whether the design continues.

        Returns:
            The number of blocking findings and the next step, or that the design is finished and why.
        """
        session = ctx.deps
        if not session.test_cases:
            raise ModelRetry("There are no test cases to review; generate them first.")
        if session.stop_reason is not None:
            raise ModelRetry("The design is finished; publish the test cases next.")
        if session.iteration > session.fixes:
            raise ModelRetry("The test cases are already reviewed; fix them next.")
        usage_limits = self.get_sub_agent_usage_limits()
        await self.reviewer.review_changed(session, ctx.usage, usage_limits)
        await self.reviewer.review_set(session, ctx.usage, usage_limits)
        session.iteration += 1
        blocking_count = len(session.blocking_findings(self.fix_min_severity))
        session.stop_reason = self._stop_reason(session, blocking_count)
        session.previous_blocking_count = blocking_count
        logger.info(
            "Review iteration %d of %s: %d blocking finding(s), stop reason: %s.",
            session.iteration,
            session.story_key,
            blocking_count,
            session.stop_reason,
        )
        if session.stop_reason is None:
            return f"Review iteration {session.iteration}: {blocking_count} blocking finding(s); fix next."
        gaps = [
            finding for finding in session.suite_findings if finding.action is TestCaseReviewFindingAction.ADD_TEST_CASE
        ]
        if restored := session.restore_named_by(gaps):
            # A restored test case covers its gap, so the gap is no open finding of the published test set.
            session.suite_findings = [
                finding for finding in session.suite_findings if not set(finding.related_test_case_ids) & set(restored)
            ]
            logger.info("Restored %s of %s after the final review.", restored, session.story_key)
        return f"Finished ({session.stop_reason.value}); publish next."

    def _stop_reason(self, session: TestCaseDesignSession, blocking_count: int) -> DesignStopReason | None:
        """Why the review loop stops after this review, by precedence, or None when it continues."""
        if blocking_count == 0:
            return DesignStopReason.CONVERGED
        if session.iteration >= self.max_iterations:
            return DesignStopReason.ITERATION_LIMIT
        if session.previous_blocking_count is not None and blocking_count >= session.previous_blocking_count:
            return DesignStopReason.NO_PROGRESS
        return None

    async def fix_test_cases(self, ctx: RunContext[TestCaseDesignSession]) -> str:
        """
        Fixes the test cases according to the blocking findings of the last review.

        Returns:
            A summary of the modified, added and deleted test cases.
        """
        session = ctx.deps
        if session.fixes >= session.iteration:
            raise ModelRetry("The test cases are already fixed; review them next.")
        summary = await self.generator.fix(session, ctx.usage, self.get_sub_agent_usage_limits())
        session.fixes += 1
        return summary

    async def publish_test_cases(self, ctx: RunContext[TestCaseDesignSession]) -> str:
        """
        Checks the final test cases for duplicates, saves them in the test management system, classifies them, and
        publishes the review of each test case with its status; a repeated call resumes after the last completed step.

        Returns:
            The number of published test cases.
        """
        session = ctx.deps
        if session.published:
            raise ModelRetry("The test cases are already published; return the final result next.")
        try:
            await self.reviewer.check_duplicates(session, ctx.usage, self.get_sub_agent_usage_limits())
        except TestCaseDuplicateCheckError as exc:
            raise ModelRetry(f"{exc}. Publish the test cases again to repeat the failed checks.") from exc
        with _resumable_write(session):
            await upload_test_cases(session)
        # A provider error in the classification reruns the design, which resumes here without a second upload.
        if not session.classified:
            await self._classify(session, ctx.usage)
        with _resumable_write(session):
            # One call at a time: the comment and the status do a read-modify-write PUT on the same test case.
            for test_case_key in session.test_cases:
                await add_review_feedback(session, test_case_key)
                await set_test_case_status_to_review_complete(session, test_case_key)
        session.published = True
        return f"Published {len(session.test_cases)} test case(s)."

    async def _classify(self, session: TestCaseDesignSession, usage: RunUsage) -> None:
        test_cases = utils.json_list(session.test_cases.values())
        await self.classification_agent.run_delegated(
            f"Test cases:\n```{test_cases}```", TestCaseKeys(issue_keys=list(session.test_cases)), usage
        )
        session.classified = True


class _StoryFetchingToolset(WrapperToolset[TestCaseDesignSession]):
    """The Jira issue tool of the model, limited to the design's user story, whose content it stores in the session."""

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[TestCaseDesignSession],
        tool: ToolsetTool[TestCaseDesignSession],
    ) -> str:
        session = ctx.deps
        if tool_args.get("issue_key") != session.story_key:
            raise ModelRetry(f"Fetch only the user story {session.story_key}.")
        if session.story_content is not None:
            raise ModelRetry("The user story is already fetched; continue with the next step.")
        issue = await super().call_tool(name, tool_args, ctx, tool)
        # The MCP client parses a JSON text result into a dict, but returns it unparsed when it is wrapped as a string.
        content = issue if isinstance(issue, str) else json.dumps(issue)
        session.story_id = _JiraIssue.model_validate_json(content).id
        session.story_content = content
        # The story reaches the sub-agents from the session, so it stays out of the design's own context.
        return f"Fetched the user story {session.story_key}."


@contextmanager
def _resumable_write(session: TestCaseDesignSession) -> Iterator[None]:
    """Turns a failed write into a request to publish again, which resumes after the last completed write."""
    try:
        yield
    except Exception as exc:
        # The tool is the boundary of the write: any client error is retried by the model within its retry budget.
        logger.exception("Publishing the test cases of %s failed.", session.story_key)
        raise ModelRetry(f"Publishing failed: {exc}. Publish the test cases again to resume.") from exc


async def _hide_outside_fix_loop(
    ctx: RunContext[TestCaseDesignSession], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Offers the fix only between the first review and the end of the review loop."""
    in_fix_loop = ctx.deps is not None and ctx.deps.iteration > 0 and ctx.deps.stop_reason is None
    return tool_def if in_fix_loop else None


async def _hide_until_stopped(
    ctx: RunContext[TestCaseDesignSession], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Offers the publish only after the review loop, so a failure before it writes nothing."""
    return None if ctx.deps is None or ctx.deps.stop_reason is None else tool_def


def _story_instructions(ctx: RunContext[TestCaseDesignSession]) -> str:
    if ctx.deps is None:
        raise ValueError("A test case design needs the story key as its structured data part.")
    story_instruction = f"The key of the Jira user story of this design is {ctx.deps.story_key}."
    if additional_fields_instruction := build_additional_fields_instruction():
        return f"{story_instruction}\n\n{additional_fields_instruction}"
    return story_instruction


def _complete_result(ctx: RunContext[TestCaseDesignSession], output: TestCaseDesignResult) -> TestCaseDesignResult:
    """Accepts the final result only after every step of the design, and fills it from the session.

    Raises:
        DesignAbortedError: If the result is returned before the design is complete and carries the model's comment.
        ModelRetry: If the result is returned before the design is complete without a comment.
    """
    session = ctx.deps
    missing: list[str] = []
    if session.stop_reason is None:
        missing.append("finish the review loop")
    if not session.published:
        missing.append("publish the test cases")
    if missing and output.llm_comments:
        raise DesignAbortedError(
            f"The design of {session.story_key} was aborted ({output.llm_comments}); steps not done: {'; '.join(missing)}."
        )
    if missing:
        raise ModelRetry(f"The design is not complete yet: {'; '.join(missing)}.")
    output.test_case_keys = list(session.test_cases)
    output.iterations = session.iteration
    output.stop_reason = session.stop_reason
    return output


agent = TestCaseDesignAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()

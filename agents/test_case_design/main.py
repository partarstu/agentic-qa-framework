# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.settings import ThinkingLevel
from pydantic_ai.tools import Tool, ToolDefinition

import config
from agents.test_case_classification import main as classification_main
from agents.test_case_design.prompt import TestCaseDesignSystemPrompt
from agents.test_case_generation import main as generation_main
from agents.test_case_review import main as review_main
from common import utils
from common.agent_base import AgentBase
from common.models import (
    AgentSkillDeclaration,
    DesignStopReason,
    FindingSeverity,
    TestCaseDesignResult,
    TestCaseDesignSession,
)
from common.services.test_management_tools import (
    add_review_feedback,
    set_test_case_status_to_review_complete,
    upload_test_cases,
)
from orchestrator.prompt import build_additional_fields_instruction

logger = utils.get_logger("test_case_design_agent")


class DesignAbortedError(Exception):
    """Raised when the model gives up on the design after an unrecoverable error; it fails the task without retries."""


class TestCaseDesignAgent(AgentBase):
    __test__ = False

    def __init__(self):
        self.generation_agent = generation_main.agent
        self.review_agent = review_main.agent
        self.classification_agent = classification_main.agent
        self.max_iterations = config.TestCaseDesignAgentConfig.MAX_ITERATIONS
        self.fix_min_severity = FindingSeverity(config.TestCaseDesignAgentConfig.FIX_MIN_SEVERITY)
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
            skill=AgentSkillDeclaration(
                id=config.TestCaseDesignAgentConfig.SKILL_ID,
                name=config.TestCaseDesignAgentConfig.SKILL_NAME,
                description=config.TestCaseDesignAgentConfig.SKILL_DESCRIPTION,
            ),
            tools=[
                self.generate_test_cases,
                self.review_test_cases,
                Tool(self.fix_test_cases, prepare=_hide_outside_fix_loop),
                # The writes run one call at a time: two of them do a read-modify-write PUT on the same test case.
                Tool(upload_test_cases, sequential=True, prepare=_hide_until_stopped),
                Tool(self.classify_test_cases, sequential=True, prepare=_hide_until_stopped),
                Tool(add_review_feedback, sequential=True, prepare=_hide_until_stopped),
                Tool(set_test_case_status_to_review_complete, sequential=True, prepare=_hide_until_stopped),
                Tool(self.review_agent.index_test_cases, sequential=True, prepare=_hide_until_stopped),
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

    async def generate_test_cases(self, ctx: RunContext[TestCaseDesignSession]) -> str:
        """
        Generates the test cases of the user story as drafts of the design.

        Returns:
            A summary of the generation.
        """
        session = ctx.deps
        if session.test_cases:
            raise ModelRetry("The test cases are already generated; review them next.")
        prompt = f"Generate the test cases of the Jira user story {session.story_key}."
        if additional_fields_instruction := build_additional_fields_instruction():
            prompt = f"{prompt}\n\n{additional_fields_instruction}"
        summary = await self.generation_agent.run_delegated(prompt, session, ctx.usage)
        logger.info("Generated %d test case(s) of %s.", len(session.test_cases), session.story_key)
        return summary

    async def review_test_cases(self, ctx: RunContext[TestCaseDesignSession]) -> str:
        """
        Reviews the new and changed test cases and the whole set, and decides whether the design continues.

        Returns:
            The number of blocking findings and whether the design continues with a fix or is finished.
        """
        session = ctx.deps
        if not session.test_cases:
            raise ModelRetry("There are no test cases to review; generate them first.")
        if session.stop_reason is not None:
            raise ModelRetry("The design is finished; save the test cases next.")
        if session.iteration > session.fixes:
            raise ModelRetry("The test cases are already reviewed; fix them next.")
        session.suite_reviewed = False
        summary = await self.review_agent.run_delegated(
            f"Review the test cases of the Jira user story {session.story_key}.", session, ctx.usage
        )
        if session.changed_test_case_ids:
            raise ModelRetry(f"The review left test cases unreviewed: {sorted(session.changed_test_case_ids)}.")
        if not session.suite_reviewed:
            raise ModelRetry("The review skipped the whole set of test cases; review the test cases again.")
        session.iteration += 1
        blocking = session.blocking_findings(self.fix_min_severity)
        if not blocking:
            session.stop_reason = DesignStopReason.CONVERGED
        elif session.iteration >= self.max_iterations:
            session.stop_reason = DesignStopReason.ITERATION_LIMIT
        logger.info(
            "Review iteration %d of %s: %d blocking finding(s), stop reason: %s.",
            session.iteration,
            session.story_key,
            len(blocking),
            session.stop_reason,
        )
        outcome = (
            f"The design is finished ({session.stop_reason.value})."
            if session.stop_reason
            else "The design continues: fix the test cases next."
        )
        return f"Review iteration {session.iteration}: {len(blocking)} blocking finding(s). {outcome} {summary}"

    async def fix_test_cases(self, ctx: RunContext[TestCaseDesignSession]) -> str:
        """
        Fixes the test cases according to the blocking findings of the last review.

        Returns:
            A summary of the modified, added and deleted test cases.
        """
        session = ctx.deps
        if session.fixes >= session.iteration:
            raise ModelRetry("The test cases are already fixed; review them next.")
        summary = await self.generation_agent.run_delegated(
            f"Fix the test cases of the Jira user story {session.story_key}.", session, ctx.usage
        )
        session.fixes += 1
        return summary

    async def classify_test_cases(self, ctx: RunContext[TestCaseDesignSession]) -> str:
        """
        Classifies the saved test cases and labels them accordingly.

        Returns:
            A summary of the classification.
        """
        session = ctx.deps
        if not session.uploaded:
            raise ModelRetry("Save the test cases first; only saved test cases are classified.")
        if session.classified:
            raise ModelRetry("The test cases are already classified; never classify them twice.")
        test_cases = "\n".join(str(test_case) for test_case in session.test_cases.values())
        summary = await self.classification_agent.run_delegated(f"Test cases:\n{test_cases}", session, ctx.usage)
        session.classified = True
        return summary


async def _hide_outside_fix_loop(
    ctx: RunContext[TestCaseDesignSession], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Offers the fix only between the first review and the end of the review loop."""
    in_fix_loop = ctx.deps is not None and ctx.deps.iteration > 0 and ctx.deps.stop_reason is None
    return tool_def if in_fix_loop else None


async def _hide_until_stopped(
    ctx: RunContext[TestCaseDesignSession], tool_def: ToolDefinition
) -> ToolDefinition | None:
    """Offers a write tool only after the review loop, so a failure before it writes nothing."""
    return None if ctx.deps is None or ctx.deps.stop_reason is None else tool_def


def _story_instructions(ctx: RunContext[TestCaseDesignSession]) -> str:
    if ctx.deps is None:
        raise ValueError("A test case design needs the test case design session as its structured data part.")
    return f"The key of the Jira user story of this design is {ctx.deps.story_key}."


def _complete_result(ctx: RunContext[TestCaseDesignSession], output: TestCaseDesignResult) -> TestCaseDesignResult:
    """Accepts the final result only after every step of the design, and fills it from the session.

    Raises:
        DesignAbortedError: If the result is returned before the design is complete and carries the model's comment.
        ModelRetry: If the result is returned before the design is complete without a comment.
    """
    session = ctx.deps
    keys = set(session.test_cases)
    missing: list[str] = []
    if session.stop_reason is None:
        missing.append("finish the review loop")
    if not session.uploaded:
        missing.append("save the test cases")
    if not session.classified:
        missing.append("classify the saved test cases")
    if without_feedback := sorted(keys - session.feedback_added_ids):
        missing.append(f"add the review feedback of {without_feedback}")
    if without_status := sorted(keys - session.review_completed_ids):
        missing.append(f"set the status of {without_status}")
    if not session.indexed:
        missing.append("index the saved test cases")
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

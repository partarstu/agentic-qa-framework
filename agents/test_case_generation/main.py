# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.messages import BinaryContent
from pydantic_ai.settings import ThinkingLevel
from pydantic_ai.usage import RunUsage

import config
from agents.test_case_generation.prompt import (
    AcExtractionPrompt,
    StepsGenerationPrompt,
    TestCaseCreationPrompt,
    TestCaseFixerPrompt,
    TestCaseGenerationSystemPrompt,
)
from common import utils
from common.agent_base import AgentBase
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import (
    AcceptanceCriteriaList,
    AgentSkillDeclaration,
    FindingAction,
    FindingSeverity,
    GeneratedTestCases,
    ReviewFinding,
    TestCase,
    TestCaseDesignSession,
    TestStepsSequenceList,
)
from common.services.atlassian_mcp import build_atlassian_mcp_server_toolset
from common.services.atlassian_tools import JIRA_GET_ISSUE
from common.services.jira_attachments import attachment_parts, fetch_session_attachments

logger = utils.get_logger("test_case_generation_agent")

# Attachments arrive through the REST downloader and uploads go to the test management system.
_JIRA_TOOL_ALLOWLIST = (JIRA_GET_ISSUE,)


class TestCaseGenerationAgent(AgentBase):
    __test__ = False

    def __init__(self):
        # Initialize sub-agent prompts
        self.ac_extraction_prompt = AcExtractionPrompt()
        self.steps_generation_prompt = StepsGenerationPrompt()
        self.test_case_creation_prompt = TestCaseCreationPrompt()

        # Initialize sub-agents
        model_name = config.TestCaseGenerationAgentConfig.MODEL_NAME

        self.ac_extractor_agent = CustomLlmWrapper.create_agent(
            model_name=model_name,
            output_type=AcceptanceCriteriaList,
            system_prompt=self.ac_extraction_prompt.get_prompt(),
            name="ac_extractor",
            max_output_tokens=config.TestCaseGenerationAgentConfig.MAX_OUTPUT_TOKENS,
            thinking_level=config.TestCaseGenerationAgentConfig.THINKING_LEVEL,
        )

        self.steps_generator_agent = CustomLlmWrapper.create_agent(
            model_name=model_name,
            output_type=TestStepsSequenceList,
            system_prompt=self.steps_generation_prompt.get_prompt(),
            name="steps_generator",
            max_output_tokens=config.TestCaseGenerationAgentConfig.MAX_OUTPUT_TOKENS,
            thinking_level=config.TestCaseGenerationAgentConfig.THINKING_LEVEL,
        )

        self.test_case_creator_agent = CustomLlmWrapper.create_agent(
            model_name=model_name,
            output_type=GeneratedTestCases,
            system_prompt=self.test_case_creation_prompt.get_prompt(),
            name="test_case_creator",
            max_output_tokens=config.TestCaseGenerationAgentConfig.MAX_OUTPUT_TOKENS,
            thinking_level=config.TestCaseGenerationAgentConfig.THINKING_LEVEL,
        )

        self.test_case_fixer_agent = CustomLlmWrapper.create_agent(
            model_name=model_name,
            output_type=TestCase,
            system_prompt=TestCaseFixerPrompt().get_prompt(),
            name="test_case_fixer",
            max_output_tokens=config.TestCaseGenerationAgentConfig.MAX_OUTPUT_TOKENS,
            thinking_level=config.TestCaseGenerationAgentConfig.THINKING_LEVEL,
        )
        self.fix_min_severity = FindingSeverity(config.TestCaseDesignAgentConfig.FIX_MIN_SEVERITY)

        # Initialize base agent (as orchestrator placeholder)
        instruction_prompt = TestCaseGenerationSystemPrompt()
        super().__init__(
            agent_name=config.TestCaseGenerationAgentConfig.OWN_NAME,
            base_url=config.AGENT_BASE_URL,
            port=config.TestCaseGenerationAgentConfig.PORT,
            external_port=config.TestCaseGenerationAgentConfig.EXTERNAL_PORT,
            protocol=config.TestCaseGenerationAgentConfig.PROTOCOL,
            model_name=config.TestCaseGenerationAgentConfig.MODEL_NAME,
            version=config.TestCaseGenerationAgentConfig.VERSION,
            max_output_tokens=config.TestCaseGenerationAgentConfig.MAX_OUTPUT_TOKENS,
            output_type=GeneratedTestCases,
            instructions=instruction_prompt.get_prompt(),
            mcp_toolset_factories=[lambda: build_atlassian_mcp_server_toolset(_JIRA_TOOL_ALLOWLIST)],
            deps_type=TestCaseDesignSession,
            skill=AgentSkillDeclaration(
                id=config.TestCaseGenerationAgentConfig.SKILL_ID,
                name=config.TestCaseGenerationAgentConfig.SKILL_NAME,
                description=config.TestCaseGenerationAgentConfig.SKILL_DESCRIPTION,
            ),
            tools=[self._generate_test_cases, self.fix_test_cases],
        )

    def get_thinking_level(self) -> ThinkingLevel:
        return config.TestCaseGenerationAgentConfig.THINKING_LEVEL

    def get_max_requests_per_task(self) -> int:
        return config.TestCaseGenerationAgentConfig.MAX_REQUESTS_PER_TASK

    async def _generate_test_cases(
        self, ctx: RunContext[TestCaseDesignSession], jira_issue_id: int, jira_issue_content: str
    ) -> GeneratedTestCases:
        """
        Generates the test cases of the Jira issue based on its content and attachments, and adds them to the design.

        Args:
            jira_issue_id: The numeric ID of the Jira issue (not its key), e.g. 10020.
            jira_issue_content: The whole content of the Jira issue.

        Returns:
            The generated test cases, each with its draft ID as key.
        """
        session = ctx.deps
        if session.test_cases:
            raise ModelRetry("The test cases are already generated; never generate them twice.")
        session.story_id = jira_issue_id
        session.story_content = jira_issue_content
        attachments_content = await fetch_session_attachments(session)
        extracted_acceptance_criteria = await self.extract_acceptance_criteria(
            attachments_content, jira_issue_content, ctx.usage
        )
        test_steps_sequences = await self.generate_test_steps(
            extracted_acceptance_criteria, attachments_content, ctx.usage
        )
        generated_test_cases = await self.create_test_cases_from_steps(
            extracted_acceptance_criteria, jira_issue_content, test_steps_sequences, ctx.usage
        )
        draft_ids = [session.add_draft(test_case) for test_case in generated_test_cases.test_cases]
        return GeneratedTestCases(
            test_cases=[session.test_cases[draft_id].model_copy(update={"key": draft_id}) for draft_id in draft_ids],
            llm_comments=generated_test_cases.llm_comments,
        )

    async def fix_test_cases(self, ctx: RunContext[TestCaseDesignSession]) -> str:
        """
        Fixes the test cases of the design according to the blocking findings of their last review: modifies the
        affected test cases, deletes the redundant ones and adds the missing ones.

        Returns:
            A summary of the modified, added and deleted test cases.
        """
        session = ctx.deps
        blocking = session.blocking_findings(self.fix_min_severity)
        if not blocking:
            return "No finding blocks the test cases, so there is nothing to fix."
        deleted = _delete_redundant_test_cases(session, blocking)
        findings_by_owner = _findings_by_owner(session, blocking)
        missing = [finding for finding in blocking if finding.action is FindingAction.ADD_TEST_CASE]
        logger.info(
            "Fixing %d test case(s), adding %d and deleting %d.", len(findings_by_owner), len(missing), len(deleted)
        )
        fixed, new_test_cases = await self._run_fixers(session, findings_by_owner, missing, ctx.usage)

        for owner, test_case in fixed.items():
            session.test_cases[owner] = test_case.model_copy(update={"key": session.test_cases[owner].key})
            session.changed_test_case_ids.add(owner)
        added = [session.add_draft(test_case) for test_case in new_test_cases]
        # The fixes resolved every blocking finding, so a repeated call cannot fix or add the same thing twice.
        session.drop_blocking_findings(self.fix_min_severity)
        return (
            f"Modified test cases: {', '.join(fixed) or 'none'}; added: {', '.join(added) or 'none'}; "
            f"deleted: {', '.join(sorted(deleted)) or 'none'}."
        )

    async def _run_fixers(
        self,
        session: TestCaseDesignSession,
        findings_by_owner: dict[str, list[ReviewFinding]],
        missing: list[ReviewFinding],
        usage: RunUsage,
    ) -> tuple[dict[str, TestCase], list[TestCase]]:
        """Runs one fixer per affected test case and one per missing test case, returning the fixed and the new ones."""
        context_parts = [
            f"Jira Issue content:\n```{session.story_content}```",
            *attachment_parts(await fetch_session_attachments(session)),
        ]
        usage_limits = self.get_sub_agent_usage_limits()

        async def run_fixer(request: list[str]) -> TestCase:
            result = await self.test_case_fixer_agent.run(
                [*request, *context_parts], usage=usage, usage_limits=usage_limits
            )
            return result.output

        # Every fix touches a single test case, so the fixer runs are independent of each other.
        async with asyncio.TaskGroup() as task_group:
            fixes = {
                owner: task_group.create_task(run_fixer(_fix_request(session, owner, findings)))
                for owner, findings in findings_by_owner.items()
            }
            additions = [task_group.create_task(run_fixer(_addition_request(session, finding))) for finding in missing]
        return {owner: fix.result() for owner, fix in fixes.items()}, [addition.result() for addition in additions]

    async def create_test_cases_from_steps(
        self,
        extracted_acceptance_criteria: AcceptanceCriteriaList,
        jira_issue_content: str,
        test_steps_sequences: TestStepsSequenceList,
        usage: RunUsage,
    ) -> GeneratedTestCases:
        logger.info("Generating Test Cases for all step sequences")
        user_message = f"""
Jira Issue content:
{jira_issue_content}


Acceptance Criteria Items:
{extracted_acceptance_criteria.model_dump_json()}


Test Step Sequences:
{test_steps_sequences.model_dump_json()}
"""
        result = await self.test_case_creator_agent.run(
            user_message, usage=usage, usage_limits=self.get_sub_agent_usage_limits()
        )
        generated_test_cases: GeneratedTestCases = result.output
        logger.info(f"Generated {len(generated_test_cases.test_cases)} test cases.")
        return generated_test_cases

    async def generate_test_steps(
        self,
        extracted_acceptance_criteria: AcceptanceCriteriaList,
        attachments_content: dict[str, BinaryContent],
        usage: RunUsage,
    ) -> TestStepsSequenceList:
        """The steps are built from the criteria and the original attachments: a criterion carries what the
        issue text adds to it, while the attachments are handed over as they are, not as a summary."""
        logger.info("Generating Steps for all ACs with %d attachments", len(attachments_content))
        user_message_parts: list[str | BinaryContent] = [
            f"Acceptance Criteria Items:\n{extracted_acceptance_criteria.model_dump_json()}",
            *attachment_parts(attachments_content),
        ]
        result = await self.steps_generator_agent.run(
            user_message_parts, usage=usage, usage_limits=self.get_sub_agent_usage_limits()
        )
        test_steps_sequences: TestStepsSequenceList = result.output
        logger.info(
            f"Generated {len(test_steps_sequences.items)} test step sequences with total "
            f"of {sum(len(s.steps) for s in test_steps_sequences.items)} steps."
        )
        return test_steps_sequences

    async def extract_acceptance_criteria(
        self, attachments_content: dict[str, BinaryContent], jira_issue_content: str, usage: RunUsage
    ) -> AcceptanceCriteriaList:
        user_message_parts: list[str | BinaryContent] = [
            f"Jira Issue content:\n{jira_issue_content}",
            *attachment_parts(attachments_content),
        ]
        logger.info("Starting AC extraction with %d attachments", len(attachments_content))
        # Own, short-lived Jira MCP session for this sub-agent run, as for the main agent.
        async with build_atlassian_mcp_server_toolset(_JIRA_TOOL_ALLOWLIST) as jira_toolset:
            result = await self.ac_extractor_agent.run(
                user_message_parts,
                toolsets=[jira_toolset],
                usage=usage,
                usage_limits=self.get_sub_agent_usage_limits(),
            )
        extracted_acceptance_criteria: AcceptanceCriteriaList = result.output
        logger.info(f"Extracted {len(extracted_acceptance_criteria.items)} ACs")
        return extracted_acceptance_criteria


def _delete_redundant_test_cases(session: TestCaseDesignSession, blocking: list[ReviewFinding]) -> set[str]:
    """Deletes the test cases which a blocking finding marks for deletion and returns their IDs."""
    deleted = {
        finding.owner_test_case_id
        for finding in blocking
        if finding.action is FindingAction.DELETE_TEST_CASE and finding.owner_test_case_id in session.test_cases
    }
    for test_case_id in deleted:
        del session.test_cases[test_case_id]
        session.findings.pop(test_case_id, None)
        session.changed_test_case_ids.discard(test_case_id)
    return deleted


def _findings_by_owner(session: TestCaseDesignSession, blocking: list[ReviewFinding]) -> dict[str, list[ReviewFinding]]:
    """The blocking findings which change an existing test case, grouped by that test case."""
    findings_by_owner: dict[str, list[ReviewFinding]] = {}
    for finding in blocking:
        if finding.action is not FindingAction.ADD_TEST_CASE and finding.owner_test_case_id in session.test_cases:
            findings_by_owner.setdefault(finding.owner_test_case_id, []).append(finding)
    return findings_by_owner


def _other_test_cases(session: TestCaseDesignSession, excluded_id: str | None = None) -> str:
    return "\n".join(
        f"ID {test_case_id}:\n{test_case}"
        for test_case_id, test_case in session.test_cases.items()
        if test_case_id != excluded_id
    )


def _fix_request(session: TestCaseDesignSession, test_case_id: str, findings: list[ReviewFinding]) -> list[str]:
    return [
        f"Test case to fix (ID {test_case_id}):\n```{session.test_cases[test_case_id]!s}```",
        "Findings to resolve:\n```[" + ", ".join(finding.model_dump_json() for finding in findings) + "]```",
        f"Other test cases of the design (context only):\n```{_other_test_cases(session, test_case_id)}```",
    ]


def _addition_request(session: TestCaseDesignSession, finding: ReviewFinding) -> list[str]:
    return [
        f"Finding which describes a missing test case:\n```{finding.model_dump_json()}```",
        f"Test cases of the design (context only):\n```{_other_test_cases(session)}```",
    ]


agent = TestCaseGenerationAgent()

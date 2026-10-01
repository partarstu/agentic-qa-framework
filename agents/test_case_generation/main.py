# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from functools import partial

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.messages import BinaryContent
from pydantic_ai.usage import RunUsage, UsageLimits

import config
from agents.test_case_generation.prompt import (
    AcExtractionPrompt,
    StepsGenerationPrompt,
    TestCaseCreationPrompt,
    TestCaseFixerPrompt,
)
from common import utils
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import (
    AcceptanceCriteriaList,
    DeletedTestCase,
    DesignedTestCase,
    FindingAction,
    FindingSeverity,
    GeneratedTestCases,
    PreviousReview,
    ReviewFinding,
    TestCaseDesignSession,
    TestStepsSequenceList,
)
from common.services.jira_attachments import attachment_parts, fetch_session_attachments, story_context_parts
from common.services.test_case_index import render_designed_test_case_text

logger = utils.get_logger("test_case_generation_agent")


class TestCaseGenerator:
    """Generates the test cases of a design and fixes them according to the findings of their review."""

    __test__ = False

    def __init__(self) -> None:
        self.ac_extraction_prompt = AcExtractionPrompt()
        self.steps_generation_prompt = StepsGenerationPrompt()
        self.test_case_creation_prompt = TestCaseCreationPrompt()
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
            deps_type=TestCaseDesignSession,
            max_output_tokens=config.TestCaseGenerationAgentConfig.MAX_OUTPUT_TOKENS,
            thinking_level=config.TestCaseGenerationAgentConfig.THINKING_LEVEL,
        )
        self.test_case_creator_agent.output_validator(_require_known_ac_ids)

        self.test_case_fixer_agent = CustomLlmWrapper.create_agent(
            model_name=model_name,
            output_type=DesignedTestCase,
            system_prompt=TestCaseFixerPrompt().get_prompt(),
            name="test_case_fixer",
            deps_type=TestCaseDesignSession,
            max_output_tokens=config.TestCaseGenerationAgentConfig.MAX_OUTPUT_TOKENS,
            thinking_level=config.TestCaseGenerationAgentConfig.THINKING_LEVEL,
        )
        self.test_case_fixer_agent.output_validator(_require_known_ac_ids)
        self.fix_min_severity = FindingSeverity(config.TestCaseDesignAgentConfig.FIX_MIN_SEVERITY)

    async def generate(self, session: TestCaseDesignSession, usage: RunUsage, usage_limits: UsageLimits) -> None:
        """Generates the test cases of the fetched story and stores them in the design as drafts."""
        attachments = await fetch_session_attachments(session)
        extracted = await self.extract_acceptance_criteria(attachments, session.story_content, usage, usage_limits)
        session.acceptance_criteria = extracted.items
        context_parts = await story_context_parts(session)
        test_steps_sequences = await self.generate_test_steps(context_parts, usage, usage_limits)
        generated = await self.create_test_cases_from_steps(
            session, context_parts, test_steps_sequences, usage, usage_limits
        )
        for test_case in generated.test_cases:
            session.add_draft(test_case)

    async def fix(self, session: TestCaseDesignSession, usage: RunUsage, usage_limits: UsageLimits) -> str:
        """Modifies, deletes, restores and adds test cases of the design according to the blocking findings."""
        blocking = session.blocking_findings(self.fix_min_severity)
        if not blocking:
            return "No finding blocks the test cases, so there is nothing to fix."
        gaps = [finding for finding in blocking if finding.action is FindingAction.ADD_TEST_CASE]
        # Restored before this fix deletes anything, so a gap never undoes a deletion of the same review.
        restored = session.restore_named_by(gaps)
        deleted = _delete_test_cases(session, blocking)
        missing = [gap for gap in gaps if not set(gap.related_test_case_ids) & set(restored)]
        findings_by_owner = _findings_by_owner(session, blocking)
        logger.info(
            "Fixing %d test case(s), adding %d, deleting %d and restoring %d.",
            len(findings_by_owner),
            len(missing),
            len(deleted),
            len(restored),
        )
        fixed, new_test_cases = await self._run_fixers(session, findings_by_owner, missing, usage, usage_limits)

        for owner, test_case in fixed.items():
            previous = session.test_cases[owner]
            session.previous_reviews[owner] = PreviousReview(
                test_case=previous, findings=session.findings.get(owner, [])
            )
            session.test_cases[owner] = test_case.model_copy(update={"key": previous.key})
            session.changed_test_case_ids.add(owner)
        added = [session.add_draft(test_case) for test_case in new_test_cases]
        # The fixes resolved every blocking finding, so a repeated call cannot fix or add the same thing twice.
        session.drop_blocking_findings(self.fix_min_severity)
        return (
            f"Modified test cases: {', '.join(fixed) or 'none'}; added: {', '.join(added) or 'none'}; "
            f"deleted: {', '.join(sorted(deleted)) or 'none'}; restored: {', '.join(restored) or 'none'}."
        )

    async def _run_fixers(
        self,
        session: TestCaseDesignSession,
        findings_by_owner: dict[str, list[ReviewFinding]],
        missing: list[ReviewFinding],
        usage: RunUsage,
        usage_limits: UsageLimits,
    ) -> tuple[dict[str, DesignedTestCase], list[DesignedTestCase]]:
        """Runs one fixer per affected test case and one per missing test case, returning the fixed and the new ones."""
        context_parts = await story_context_parts(session)

        async def run_fixer(request: list[str]) -> DesignedTestCase:
            result = await self.test_case_fixer_agent.run(
                [*context_parts, *request], deps=session, usage=usage, usage_limits=usage_limits
            )
            return result.output

        requests = [_fix_request(session, owner, findings) for owner, findings in findings_by_owner.items()]
        requests += [
            _addition_request(session, gap, [other for other in missing if other is not gap]) for gap in missing
        ]
        # Every fix touches a single test case, so the fixer runs are independent of each other.
        results = await utils.run_first_then_concurrently([partial(run_fixer, request) for request in requests])
        fixes, additions = results[: len(findings_by_owner)], results[len(findings_by_owner) :]
        return dict(zip(findings_by_owner, fixes, strict=True)), additions

    async def create_test_cases_from_steps(
        self,
        session: TestCaseDesignSession,
        context_parts: list[str | BinaryContent],
        test_steps_sequences: TestStepsSequenceList,
        usage: RunUsage,
        usage_limits: UsageLimits,
    ) -> GeneratedTestCases:
        logger.info("Generating Test Cases for all step sequences")
        result = await self.test_case_creator_agent.run(
            [*context_parts, f"Test Step Sequences:\n{test_steps_sequences.model_dump_json()}"],
            deps=session,
            usage=usage,
            usage_limits=usage_limits,
        )
        generated_test_cases: GeneratedTestCases = result.output
        logger.info(f"Generated {len(generated_test_cases.test_cases)} test cases.")
        return generated_test_cases

    async def generate_test_steps(
        self, context_parts: list[str | BinaryContent], usage: RunUsage, usage_limits: UsageLimits
    ) -> TestStepsSequenceList:
        """Builds the steps from the story context, whose attachments reach the model as they are, not as a summary."""
        logger.info("Generating Steps for all ACs")
        result = await self.steps_generator_agent.run(context_parts, usage=usage, usage_limits=usage_limits)
        test_steps_sequences: TestStepsSequenceList = result.output
        logger.info(
            f"Generated {len(test_steps_sequences.items)} test step sequences with total "
            f"of {sum(len(s.steps) for s in test_steps_sequences.items)} steps."
        )
        return test_steps_sequences

    async def extract_acceptance_criteria(
        self,
        attachments_content: dict[str, BinaryContent],
        jira_issue_content: str | None,
        usage: RunUsage,
        usage_limits: UsageLimits,
    ) -> AcceptanceCriteriaList:
        user_message_parts: list[str | BinaryContent] = [
            f"Jira Issue content:\n{jira_issue_content}",
            *attachment_parts(attachments_content),
        ]
        logger.info("Starting AC extraction with %d attachments", len(attachments_content))
        result = await self.ac_extractor_agent.run(user_message_parts, usage=usage, usage_limits=usage_limits)
        extracted_acceptance_criteria: AcceptanceCriteriaList = result.output
        logger.info(f"Extracted {len(extracted_acceptance_criteria.items)} ACs")
        return extracted_acceptance_criteria


def _require_known_ac_ids[T: (GeneratedTestCases, DesignedTestCase)](
    ctx: RunContext[TestCaseDesignSession], output: T
) -> T:
    """Asks the model again when a test case traces to an acceptance criterion the story does not have."""
    test_cases = output.test_cases if isinstance(output, GeneratedTestCases) else [output]
    known = {criterion.id for criterion in ctx.deps.acceptance_criteria}
    if unknown := sorted({ac_id for test_case in test_cases for ac_id in test_case.ac_ids} - known):
        raise ModelRetry(f"Unknown acceptance criteria IDs {unknown}; use only {sorted(known)}.")
    return output


def _delete_test_cases(session: TestCaseDesignSession, blocking: list[ReviewFinding]) -> list[str]:
    """Deletes the test cases which a blocking finding marks for deletion, keeping each for a restore."""
    deleted: list[str] = []
    for finding in blocking:
        test_case_id = finding.owner_test_case_id
        if finding.action is FindingAction.DELETE_TEST_CASE and test_case_id in session.test_cases:
            session.deleted_test_cases[test_case_id] = DeletedTestCase(
                test_case=session.test_cases.pop(test_case_id),
                findings=session.findings.pop(test_case_id, []),
                deleted_by=finding,
            )
            session.changed_test_case_ids.discard(test_case_id)
            deleted.append(test_case_id)
    return deleted


def _findings_by_owner(session: TestCaseDesignSession, blocking: list[ReviewFinding]) -> dict[str, list[ReviewFinding]]:
    """The blocking findings which change an existing test case, grouped by that test case."""
    findings_by_owner: dict[str, list[ReviewFinding]] = {}
    for finding in blocking:
        if finding.action is not FindingAction.ADD_TEST_CASE and finding.owner_test_case_id in session.test_cases:
            findings_by_owner.setdefault(finding.owner_test_case_id, []).append(finding)
    return findings_by_owner


def _related_test_cases(session: TestCaseDesignSession, test_case_id: str, findings: list[ReviewFinding]) -> str:
    """The test cases which the findings name as related; a deleted one is marked, so that a merge can absorb it."""
    related_ids = dict.fromkeys(related_id for finding in findings for related_id in finding.related_test_case_ids)
    blocks: list[str] = []
    for related_id in related_ids:
        if related_id in session.test_cases and related_id != test_case_id:
            blocks.append(f"ID {related_id}:\n{render_designed_test_case_text(session.test_cases[related_id])}")
        elif related_id in session.deleted_test_cases:
            deleted = session.deleted_test_cases[related_id].test_case
            blocks.append(f"ID {related_id} (deleted):\n{render_designed_test_case_text(deleted)}")
    return "\n".join(blocks)


def _fix_request(session: TestCaseDesignSession, test_case_id: str, findings: list[ReviewFinding]) -> list[str]:
    request = [
        f"Test case to fix (ID {test_case_id}):\n```{session.test_cases[test_case_id]!s}```",
        f"Findings to resolve:\n```{utils.json_list(findings)}```",
    ]
    if related := _related_test_cases(session, test_case_id, findings):
        request.append(f"Related test cases of the findings (context only):\n```{related}```")
    return request


def _addition_request(session: TestCaseDesignSession, gap: ReviewFinding, siblings: list[ReviewFinding]) -> list[str]:
    test_cases = "\n".join(
        f"ID {test_case_id}:\n{render_designed_test_case_text(test_case)}"
        for test_case_id, test_case in session.test_cases.items()
    )
    request = [
        f"Finding which describes a missing test case:\n```{gap.model_dump_json()}```",
        f"Test cases of the design (context only):\n```{test_cases}```",
    ]
    if siblings:
        request.append(
            f"Other missing test cases, each created separately (never cover them):\n```{utils.json_list(siblings)}```"
        )
    return request

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
from dataclasses import dataclass
from functools import partial

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.messages import BinaryContent
from pydantic_ai.usage import RunUsage, UsageLimits

import config
from agents.test_case_design.story_context import fetch_session_attachments, story_context_parts
from agents.test_case_generation.prompt import (
    AcExtractionPrompt,
    KnowledgeAwareTestCaseGeneratorPrompt,
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
    GeneratedTestCases,
    KnowledgeAwareItem,
    KnowledgeAwareTestCase,
    PreviousReview,
    ProcedureNode,
    ProcedureSelectionResult,
    TestCaseDesignSession,
    TestCaseReviewFinding,
    TestCaseReviewFindingAction,
    TestCaseReviewFindingSeverity,
    TestStep,
    TestStepsSequenceList,
)
from common.services.jira_attachments import attachment_parts
from common.services.procedure_knowledge import (
    precondition_ids,
    procedure_nodes_by_id,
    render_procedure_knowledge,
    step_ids,
    try_select_procedures,
)
from common.services.test_case_index import render_designed_test_case_block

logger = utils.get_logger("test_case_generation_agent")


@dataclass(frozen=True, slots=True)
class _KnowledgeRebuild:
    """The draft test case a knowledge-aware rebuild works on and every recorded procedure selected for it by ID."""

    draft: DesignedTestCase
    procedures: dict[str, ProcedureNode]


@dataclass(frozen=True, slots=True)
class _RebuildOutcome:
    """The test cases after the knowledge-aware rebuild, in their order, and the positions of those without a selection."""

    test_cases: list[DesignedTestCase]
    unavailable: list[int]


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

        self.knowledge_aware_generator_agent = CustomLlmWrapper.create_agent(
            model_name=model_name,
            output_type=KnowledgeAwareTestCase,
            system_prompt=KnowledgeAwareTestCaseGeneratorPrompt().get_prompt(),
            name="knowledge_aware_test_case_generator",
            deps_type=_KnowledgeRebuild,
            max_output_tokens=config.TestCaseGenerationAgentConfig.MAX_OUTPUT_TOKENS,
            thinking_level=config.TestCaseGenerationAgentConfig.THINKING_LEVEL,
        )
        self.knowledge_aware_generator_agent.output_validator(_require_valid_rebuild)
        self.procedure_knowledge_enabled = config.TestCaseDesignAgentConfig.PROCEDURE_KNOWLEDGE_ENABLED
        if not self.procedure_knowledge_enabled:
            logger.info("Procedure knowledge is disabled: test cases are neither rebuilt from nor reviewed against it.")
        self.fix_min_severity = TestCaseReviewFindingSeverity(config.TestCaseDesignAgentConfig.FIX_MIN_SEVERITY)

    async def generate(self, session: TestCaseDesignSession, usage: RunUsage, usage_limits: UsageLimits) -> str:
        """Generates the test cases of the fetched story as drafts of the design and summarizes their coverage."""
        attachments = await fetch_session_attachments(session)
        extracted = await self.extract_acceptance_criteria(attachments, session.story_content, usage, usage_limits)
        session.acceptance_criteria = extracted.items
        context_parts = await story_context_parts(session)
        test_steps_sequences = await self.generate_test_steps(context_parts, usage, usage_limits)
        generated = await self.create_test_cases_from_steps(
            session, context_parts, test_steps_sequences, usage, usage_limits
        )
        rebuilt = await self._rebuild_with_procedures(session, context_parts, generated.test_cases, usage, usage_limits)
        drafts = {session.add_draft(test_case): test_case for test_case in rebuilt.test_cases}
        covered = {ac_id for test_case in drafts.values() for ac_id in test_case.ac_ids}
        uncovered = [criterion.id for criterion in session.acceptance_criteria if criterion.id not in covered]
        generated_summary = ", ".join(
            f"{draft_id} ({', '.join(test_case.ac_ids)})" for draft_id, test_case in drafts.items()
        )
        draft_ids = list(drafts)
        return (
            f"Extracted {len(session.acceptance_criteria)} acceptance criteria; generated test cases: "
            f"{generated_summary or 'none'}; acceptance criteria without a test case: {', '.join(uncovered) or 'none'}."
            f"{_unavailable_note([draft_ids[index] for index in rebuilt.unavailable])}"
        )

    async def fix(self, session: TestCaseDesignSession, usage: RunUsage, usage_limits: UsageLimits) -> str:
        """Modifies, deletes, restores and adds test cases of the design according to the blocking findings."""
        blocking = session.blocking_findings(self.fix_min_severity)
        if not blocking:
            return "No finding blocks the test cases, so there is nothing to fix."
        gaps = [finding for finding in blocking if finding.action is TestCaseReviewFindingAction.ADD_TEST_CASE]
        # The fixers see the restores and deletions on a copy; the session gets them only once every fixer succeeded,
        # so a fix repeated after a failed one plans the same changes instead of generating a restored test case anew.
        planned = session.model_copy(deep=True)
        # Restored before this fix deletes anything, so a gap never undoes a deletion of the same review.
        restored = planned.restore_named_by(gaps)
        deleted = _delete_test_cases(planned, blocking)
        missing = [gap for gap in gaps if not set(gap.related_test_case_ids) & set(restored)]
        findings_by_owner = _findings_by_owner(planned, blocking)
        logger.info(
            "Fixing %d test case(s), adding %d, deleting %d and restoring %d.",
            len(findings_by_owner),
            len(missing),
            len(deleted),
            len(restored),
        )
        async with asyncio.TaskGroup() as task_group:
            fixing = task_group.create_task(self._run_fixers(planned, findings_by_owner, usage, usage_limits))
            adding = task_group.create_task(self._generate_missing(planned, missing, usage, usage_limits))
        fixes, additions = fixing.result(), adding.result()
        rebuilt = await self._rebuild_with_procedures(
            planned, await story_context_parts(planned), [*fixes.values(), *additions], usage, usage_limits
        )
        fixed = dict(zip(fixes, rebuilt.test_cases[: len(fixes)], strict=True))
        new_test_cases = rebuilt.test_cases[len(fixes) :]

        session.restore_named_by(gaps)
        _delete_test_cases(session, blocking)
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
        changed_ids = [*fixed, *added]
        return (
            f"Modified test cases: {', '.join(fixed) or 'none'}; added: {', '.join(added) or 'none'}; "
            f"deleted: {', '.join(sorted(deleted)) or 'none'}; restored: {', '.join(restored) or 'none'}."
            f"{_unavailable_note([changed_ids[index] for index in rebuilt.unavailable])}"
        )

    async def _rebuild_with_procedures(
        self,
        session: TestCaseDesignSession,
        context_parts: list[str | BinaryContent],
        test_cases: list[DesignedTestCase],
        usage: RunUsage,
        usage_limits: UsageLimits,
    ) -> _RebuildOutcome:
        """Rebuild each test case from the recorded procedures selected for it; one without a selection stays as is."""
        if not self.procedure_knowledge_enabled or not test_cases:
            return _RebuildOutcome(test_cases=list(test_cases), unavailable=[])
        # The selections take minutes each, so they all run at once; the rebuilds then share the story context prefix.
        async with asyncio.TaskGroup() as task_group:
            selecting = [
                task_group.create_task(
                    try_select_procedures(test_case, f"test case '{test_case.name}' of {session.story_key}")
                )
                for test_case in test_cases
            ]
        selections = [task.result() for task in selecting]
        to_rebuild = {
            index: selection
            for index, selection in enumerate(selections)
            if selection is not None and procedure_nodes_by_id(selection)
        }
        rebuilds = await utils.run_first_then_concurrently(
            [
                partial(self._rebuild, context_parts, test_cases[index], selection, usage, usage_limits)
                for index, selection in to_rebuild.items()
            ]
        )
        rebuilt = list(test_cases)
        for index, test_case in zip(to_rebuild, rebuilds, strict=True):
            rebuilt[index] = test_case
        logger.info("Rebuilt %d of %d test case(s) from recorded procedures.", len(to_rebuild), len(test_cases))
        return _RebuildOutcome(
            test_cases=rebuilt, unavailable=[index for index, selection in enumerate(selections) if selection is None]
        )

    async def _rebuild(
        self,
        context_parts: list[str | BinaryContent],
        draft: DesignedTestCase,
        selection: ProcedureSelectionResult,
        usage: RunUsage,
        usage_limits: UsageLimits,
    ) -> DesignedTestCase:
        procedures = procedure_nodes_by_id(selection)
        result = await self.knowledge_aware_generator_agent.run(
            [
                *context_parts,
                render_designed_test_case_block("Draft test case", draft),
                f"Recorded procedures selected for the items of the draft test case:\n"
                f"```\n{render_procedure_knowledge(draft, selection)}\n```",
            ],
            deps=_KnowledgeRebuild(draft=draft, procedures=procedures),
            usage=usage,
            usage_limits=usage_limits,
        )
        return _rebuilt_test_case(draft, result.output, procedures)

    async def _run_fixers(
        self,
        session: TestCaseDesignSession,
        findings_by_owner: dict[str, list[TestCaseReviewFinding]],
        usage: RunUsage,
        usage_limits: UsageLimits,
    ) -> dict[str, DesignedTestCase]:
        """Runs one fixer per affected test case and returns the fixed test cases by their IDs."""
        context_parts = await story_context_parts(session)

        async def run_fixer(test_case_id: str, findings: list[TestCaseReviewFinding]) -> DesignedTestCase:
            result = await self.test_case_fixer_agent.run(
                [*context_parts, *_fix_request(session, test_case_id, findings)],
                deps=session,
                usage=usage,
                usage_limits=usage_limits,
            )
            return result.output

        # Every fix touches a single test case, so the fixer runs are independent of each other.
        fixes = await utils.run_first_then_concurrently(
            [partial(run_fixer, owner, findings) for owner, findings in findings_by_owner.items()]
        )
        return dict(zip(findings_by_owner, fixes, strict=True))

    async def _generate_missing(
        self,
        session: TestCaseDesignSession,
        gaps: list[TestCaseReviewFinding],
        usage: RunUsage,
        usage_limits: UsageLimits,
    ) -> list[DesignedTestCase]:
        """Generates a test case for each coverage gap the same way as the first test cases, without adding it yet."""
        if not gaps:
            return []
        context_parts = [*await story_context_parts(session), *_missing_test_cases_request(session, gaps)]
        test_steps_sequences = await self.generate_test_steps(context_parts, usage, usage_limits)
        generated = await self.create_test_cases_from_steps(
            session, context_parts, test_steps_sequences, usage, usage_limits
        )
        return generated.test_cases

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


def _require_valid_rebuild(
    ctx: RunContext[_KnowledgeRebuild], output: KnowledgeAwareTestCase
) -> KnowledgeAwareTestCase:
    """Ask the model again for an unknown procedure ID, an added test step or draft items not covered once in order."""
    rebuild = ctx.deps
    errors: list[str] = []
    reused = {item.procedure_id for item in [*output.preconditions, *output.steps] if item.procedure_id is not None}
    if unknown := sorted(reused - set(rebuild.procedures)):
        errors.append(f"Unknown procedure IDs {unknown}; use only the IDs of the given recorded procedures.")
    if any(not step.covers for step in output.steps):
        errors.append("Every test step must cover at least one draft test step; only a precondition may be added.")
    for kind, items, expected in (
        ("preconditions", output.preconditions, precondition_ids(rebuild.draft)),
        ("test steps", output.steps, step_ids(rebuild.draft)),
    ):
        if (covered := [item_id for item in items for item_id in item.covers]) != expected:
            errors.append(
                f"The {kind} cover {covered}, but must cover the draft's {kind} {expected}, each exactly once and in "
                "this order."
            )
    if errors:
        raise ModelRetry("\n".join(errors))
    return output


def _rebuilt_test_case(
    draft: DesignedTestCase, output: KnowledgeAwareTestCase, procedures: dict[str, ProcedureNode]
) -> DesignedTestCase:
    """Return the draft with the rebuilt items, taking over the reused procedures' descriptions verbatim."""

    def text(item: KnowledgeAwareItem) -> str:
        # The recorded wording, not the model's copy of it, lets the execution agent match the procedure exactly.
        return procedures[item.procedure_id].description if item.procedure_id is not None else item.text

    steps = [
        TestStep(action=text(item), expected_results=item.expected_results, test_data=item.test_data)
        for item in output.steps
    ]
    preconditions = "\n".join(text(item) for item in output.preconditions)
    return draft.model_copy(update={"preconditions": preconditions or None, "steps": steps})


def _unavailable_note(test_case_ids: list[str]) -> str:
    if not test_case_ids:
        return ""
    return f" Recorded procedures were unavailable for {', '.join(test_case_ids)}, which stay unchanged by them."


def _delete_test_cases(session: TestCaseDesignSession, blocking: list[TestCaseReviewFinding]) -> list[str]:
    """Deletes the test cases which a blocking finding marks for deletion, keeping each for a restore."""
    deleted: list[str] = []
    for finding in blocking:
        test_case_id = finding.owner_test_case_id
        if finding.action is TestCaseReviewFindingAction.DELETE_TEST_CASE and test_case_id in session.test_cases:
            session.deleted_test_cases[test_case_id] = DeletedTestCase(
                test_case=session.test_cases.pop(test_case_id),
                findings=session.findings.pop(test_case_id, []),
                deleted_by=finding,
            )
            session.changed_test_case_ids.discard(test_case_id)
            deleted.append(test_case_id)
    return deleted


def _findings_by_owner(
    session: TestCaseDesignSession, blocking: list[TestCaseReviewFinding]
) -> dict[str, list[TestCaseReviewFinding]]:
    """The blocking findings which change an existing test case, grouped by that test case."""
    findings_by_owner: dict[str, list[TestCaseReviewFinding]] = {}
    for finding in blocking:
        if (
            finding.action is not TestCaseReviewFindingAction.ADD_TEST_CASE
            and finding.owner_test_case_id in session.test_cases
        ):
            findings_by_owner.setdefault(finding.owner_test_case_id, []).append(finding)
    return findings_by_owner


def _related_test_cases(
    session: TestCaseDesignSession, test_case_id: str, findings: list[TestCaseReviewFinding]
) -> str:
    """The test cases which the findings name as related; a deleted one is marked, so that a merge can absorb it."""
    related_ids = dict.fromkeys(related_id for finding in findings for related_id in finding.related_test_case_ids)
    blocks: list[str] = []
    for related_id in related_ids:
        if related_id in session.test_cases and related_id != test_case_id:
            blocks.append(render_designed_test_case_block(f"ID {related_id}", session.test_cases[related_id]))
        elif related_id in session.deleted_test_cases:
            deleted = session.deleted_test_cases[related_id].test_case
            blocks.append(render_designed_test_case_block(f"ID {related_id} (deleted)", deleted))
    return "\n\n".join(blocks)


def _fix_request(session: TestCaseDesignSession, test_case_id: str, findings: list[TestCaseReviewFinding]) -> list[str]:
    request = [
        f"Test case to fix (ID {test_case_id}):\n```{session.test_cases[test_case_id]!s}```",
        f"Findings to resolve:\n```{utils.json_list(findings)}```",
    ]
    if related := _related_test_cases(session, test_case_id, findings):
        request.append(f"Related test cases of the findings (context only):\n\n{related}")
    return request


def _missing_test_cases_request(session: TestCaseDesignSession, gaps: list[TestCaseReviewFinding]) -> list[str]:
    existing = "\n\n".join(
        render_designed_test_case_block(f"ID {test_case_id}", test_case)
        for test_case_id, test_case in session.test_cases.items()
    )
    return [
        f"Findings which describe missing test cases:\n```{utils.json_list(gaps)}```",
        f"Existing test cases (context only):\n\n{existing}",
    ]

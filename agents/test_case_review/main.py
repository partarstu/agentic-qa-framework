# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from functools import partial

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.usage import RunUsage, UsageLimits
from qdrant_client import models as qdrant_models

import config
from agents.test_case_review.prompt import (
    TestCaseDuplicateJudgePrompt,
    TestCaseReviewWithAttachmentsPrompt,
    TestSuiteReviewPrompt,
)
from common import utils
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import (
    FindingAction,
    OverlappingTestCase,
    ReviewFinding,
    TestCaseDesignSession,
    TestCaseDuplicateCheck,
    TestCaseDuplicateJudgement,
    TestCaseReviewFeedback,
    TestSuiteReview,
)
from common.services.jira_attachments import story_context_parts
from common.services.test_case_index import IndexedTestCase, render_designed_test_case_text, render_test_case
from common.services.vector_db_service import VectorDbService

logger = utils.get_logger("test_case_review_agent")

# A single test case's review never sees the other test cases, so it may only modify its own test case.
_WHOLE_SET_ACTIONS = frozenset(
    {FindingAction.ADD_TEST_CASE, FindingAction.REMOVE_DUPLICATE_STEPS, FindingAction.DELETE_TEST_CASE}
)


class TestCaseDuplicateCheckError(RuntimeError):
    """Raised when the duplicate check cannot run; it aborts the review instead of reporting no duplicates."""

    __test__ = False


class TestCaseReviewer:
    """Reviews the test cases of a design one by one and as a whole set, and checks them for duplicates."""

    __test__ = False

    def __init__(self) -> None:
        self.review_agent = CustomLlmWrapper.create_agent(
            model_name=config.TestCaseReviewAgentConfig.MODEL_NAME,
            output_type=TestCaseReviewFeedback,
            system_prompt=TestCaseReviewWithAttachmentsPrompt().get_prompt(),
            name="review_test_cases_with_attachments",
            deps_type=TestCaseDesignSession,
            thinking_level=config.TestCaseReviewAgentConfig.THINKING_LEVEL,
            max_output_tokens=config.TestCaseReviewAgentConfig.MAX_OUTPUT_TOKENS,
        )
        self.review_agent.output_validator(_validate_test_case_review)
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
        self.vector_db_service = VectorDbService(
            config.QdrantConfig.TEST_CASES_COLLECTION_NAME,
            metadata_collection_name=config.QdrantConfig.METADATA_COLLECTION_NAME,
        )

    async def close(self) -> None:
        await self.vector_db_service.close()

    async def review_changed(self, session: TestCaseDesignSession, usage: RunUsage, usage_limits: UsageLimits) -> None:
        """Reviews the new, changed and restored test cases, verifying a fixed one against its previous review."""
        test_case_ids = [
            test_case_id for test_case_id in session.test_cases if test_case_id in session.changed_test_case_ids
        ]
        context_parts = await story_context_parts(session)
        logger.info("Reviewing %d new or changed test case(s).", len(test_case_ids))

        async def review(test_case_id: str) -> None:
            result = await self.review_agent.run(
                [*context_parts, *_review_request(session, test_case_id)],
                deps=session,
                usage=usage,
                usage_limits=usage_limits,
            )
            if result.output.llm_comments:
                logger.warning("Review of test case '%s' reported: %s", test_case_id, result.output.llm_comments)
            session.findings[test_case_id] = _owned_by(test_case_id, result.output.findings)
            session.previous_reviews.pop(test_case_id, None)

        # One sub-agent run per test case keeps the model focused on a single review target; its relation to the other
        # test cases (coverage, duplicates) is the whole-set review's, so they are left out.
        await utils.run_first_then_concurrently([partial(review, test_case_id) for test_case_id in test_case_ids])
        session.changed_test_case_ids.clear()

    async def review_set(self, session: TestCaseDesignSession, usage: RunUsage, usage_limits: UsageLimits) -> None:
        """Reviews the whole set of test cases for coverage gaps and duplicate coverage, given their own findings."""
        test_case_blocks = "\n\n".join(
            f"ID {test_case_id}:\n```{render_designed_test_case_text(test_case)}```\n"
            f"Findings of its individual review:\n```{utils.json_list(session.findings[test_case_id])}```"
            for test_case_id, test_case in session.test_cases.items()
        )
        message = [*await story_context_parts(session), f"Test cases:\n{test_case_blocks}"]
        if session.deleted_test_cases:
            deleted_blocks = "\n\n".join(
                f"ID {test_case_id}:\n```{render_designed_test_case_text(deleted.test_case)}```\n"
                f"Finding which deleted it:\n```{deleted.deleted_by.model_dump_json()}```"
                for test_case_id, deleted in session.deleted_test_cases.items()
            )
            message.append(f"Deleted test cases:\n{deleted_blocks}")
        logger.info("Reviewing the whole set of %d test case(s).", len(session.test_cases))
        result = await self.test_suite_reviewer.run(
            message,
            deps=session,
            usage=usage,
            usage_limits=usage_limits,
        )
        session.suite_findings = result.output.findings
        logger.info("The whole-set review reported %d finding(s).", len(result.output.findings))

    async def check_duplicates(self, session: TestCaseDesignSession, usage: RunUsage, usage_limits: UsageLimits) -> str:
        """Checks every test case of the design against the project's existing ones and lists the overlapping keys."""
        async with asyncio.TaskGroup() as task_group:
            checks = {
                test_case_id: task_group.create_task(
                    self._check_duplicates(
                        session.project_key,
                        render_test_case(session.project_key, test_case.model_copy(update={"key": test_case_id})),
                        usage,
                        usage_limits,
                    )
                )
                for test_case_id, test_case in session.test_cases.items()
            }
        # Stored only once every check succeeded, so a failed check leaves no partial verdicts behind.
        session.duplicate_checks.update({test_case_id: check.result() for test_case_id, check in checks.items()})
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


def _review_request(session: TestCaseDesignSession, test_case_id: str) -> list[str]:
    """The test case under review and, for a fixed one, its previous version with the findings of that review."""
    request = [
        f"Test case under review (ID {test_case_id}):\n```{render_designed_test_case_text(session.test_cases[test_case_id])}```"
    ]
    if previous := session.previous_reviews.get(test_case_id):
        request += [
            f"Previous version of the test case under review:\n```{render_designed_test_case_text(previous.test_case)}```",
            f"Findings of the review of the previous version:\n```{utils.json_list(previous.findings)}```",
        ]
    return request


def _validate_test_case_review(
    ctx: RunContext[TestCaseDesignSession], output: TestCaseReviewFeedback
) -> TestCaseReviewFeedback:
    if errors := _ac_ref_errors(output.findings, ctx.deps):
        raise ModelRetry("\n".join(errors))
    return output


def _ac_ref_errors(findings: list[ReviewFinding], session: TestCaseDesignSession) -> list[str]:
    known_ids = {criterion.id for criterion in session.acceptance_criteria}
    if unknown := sorted({finding.ac_ref for finding in findings if finding.ac_ref is not None} - known_ids):
        return [f"Unknown acceptance criteria IDs {unknown} in `ac_ref`; use only {sorted(known_ids)}."]
    return []


def _finding_errors(finding: ReviewFinding, session: TestCaseDesignSession) -> list[str]:
    """What makes a finding unusable: an owner that contradicts its action, or an ID of no usable test case."""
    owner = finding.owner_test_case_id
    errors: list[str] = []
    if finding.action is FindingAction.ADD_TEST_CASE and owner is not None:
        errors.append(f"An '{finding.action}' finding has no owner test case, but '{owner}' was given.")
    if finding.action is not FindingAction.ADD_TEST_CASE and owner is None:
        errors.append(f"A '{finding.action}' finding needs exactly one owner test case: '{finding.description}'.")
    unknown = [
        test_case_id
        for test_case_id in (owner, *finding.related_test_case_ids)
        if test_case_id is not None
        and test_case_id not in session.test_cases
        and (test_case_id == owner or test_case_id not in session.deleted_test_cases)
    ]
    if unknown:
        errors.append(f"Unknown test case IDs {unknown}; use only these: {sorted(session.test_cases)}.")
    restored = [
        test_case_id for test_case_id in finding.related_test_case_ids if test_case_id in session.deleted_test_cases
    ]
    if restored and finding.action is not FindingAction.ADD_TEST_CASE:
        errors.append(
            f"The deleted test cases {restored} may be named only by an '{FindingAction.ADD_TEST_CASE}' finding "
            f"which restores them, not by the '{finding.action}' finding of '{owner}'."
        )
    return errors


def _set_errors(findings: list[ReviewFinding], session: TestCaseDesignSession) -> list[str]:
    """What makes the findings unusable together: deletions and step removals which would lose coverage."""
    # An ownerless finding is already reported by `_finding_errors`; it takes no part in these checks.
    owned = [finding for finding in findings if finding.owner_test_case_id is not None]
    deleted = {finding.owner_test_case_id for finding in owned if finding.action is FindingAction.DELETE_TEST_CASE}
    errors: list[str] = []
    for finding in owned:
        owner = finding.owner_test_case_id
        if finding.action is FindingAction.DELETE_TEST_CASE and (
            covering := deleted & set(finding.related_test_case_ids)
        ):
            errors.append(f"'{owner}' is deleted as covered by {sorted(covering)}, which are deleted too; keep one.")
        if finding.action is FindingAction.REMOVE_DUPLICATE_STEPS and (
            gone := deleted & {owner, *finding.related_test_case_ids}
        ):
            errors.append(f"The '{finding.action}' finding of '{owner}' points at {sorted(gone)}, which is deleted.")
    for first, second in _mutual_pairs(_step_removals(owned)):
        errors.append(f"'{first}' and '{second}' remove their shared steps from each other; remove them from one only.")
    if session.test_cases and deleted >= set(session.test_cases):
        errors.append("Every test case is deleted; keep at least one.")
    return errors


def _step_removals(findings: list[ReviewFinding]) -> set[tuple[str, str]]:
    """The (owner, related) test case pairs of the `remove_duplicate_steps` findings."""
    pairs: set[tuple[str, str]] = set()
    for finding in findings:
        if finding.action is FindingAction.REMOVE_DUPLICATE_STEPS and finding.owner_test_case_id is not None:
            pairs.update((finding.owner_test_case_id, related_id) for related_id in finding.related_test_case_ids)
    return pairs


def _mutual_pairs(pairs: set[tuple[str, str]]) -> list[tuple[str, str]]:
    """Every two distinct test cases which point at each other, once per pair."""
    return [(first, second) for first, second in sorted(pairs) if first < second and (second, first) in pairs]


def _validate_test_suite_review(ctx: RunContext[TestCaseDesignSession], output: TestSuiteReview) -> TestSuiteReview:
    session = ctx.deps
    errors = [error for finding in output.findings for error in _finding_errors(finding, session)]
    errors += _set_errors(output.findings, session) + _ac_ref_errors(output.findings, session)
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

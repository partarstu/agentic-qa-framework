# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
import logging
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RunUsage, UsageLimits

from agents.test_case_review import main as review_main
from agents.test_case_review.main import TestCaseDuplicateCheckError, TestCaseReviewer
from common.models import (
    AcceptanceCriteriaItem,
    DeletedTestCase,
    DesignedTestCase,
    FindingAction,
    FindingSeverity,
    OverlappingTestCase,
    PreviousReview,
    ReviewFinding,
    TestCaseDesignSession,
    TestCaseDuplicateCheck,
    TestCaseDuplicateJudgement,
    TestCaseReviewFeedback,
    TestSuiteReview,
)

_USAGE_LIMITS = UsageLimits(request_limit=None, total_tokens_limit=1_000)
_CRITERIA = [AcceptanceCriteriaItem(id=f"AC-{n}", text=f"Criterion {n}", additional_info="") for n in (1, 2)]


@pytest.fixture
def mock_config() -> Iterator[MagicMock]:
    with patch("agents.test_case_review.main.config") as mock_conf:
        mock_conf.TestCaseReviewAgentConfig.MODEL_NAME = "test"
        mock_conf.TestCaseReviewAgentConfig.THINKING_LEVEL = "LOW"
        mock_conf.TestCaseReviewAgentConfig.MAX_OUTPUT_TOKENS = None
        mock_conf.QdrantConfig.TEST_CASES_COLLECTION_NAME = "test_cases"
        mock_conf.QdrantConfig.TEST_CASE_DUPLICATE_MAX_CANDIDATES = 5
        mock_conf.QdrantConfig.TEST_CASE_DUPLICATE_MIN_SCORE = 0.8
        yield mock_conf


@pytest.fixture
def reviewer(mock_config: MagicMock) -> TestCaseReviewer:
    test_case_reviewer = TestCaseReviewer()
    test_case_reviewer.vector_db_service = MagicMock()
    test_case_reviewer.vector_db_service.upsert_batch = AsyncMock()
    test_case_reviewer.vector_db_service.hybrid_search = AsyncMock(return_value=[])
    test_case_reviewer.duplicate_judge.run = AsyncMock()
    return test_case_reviewer


@pytest.fixture
def download() -> Iterator[MagicMock]:
    with patch("common.services.jira_attachments.download_issue_attachments", return_value={}) as mock_download:
        yield mock_download


def _test_case(name: str) -> DesignedTestCase:
    return DesignedTestCase(
        key=None,
        name=name,
        summary=f"Summary of {name}",
        steps=[],
        labels=[],
        comment="",
        preconditions="",
        parent_issue_key="PROJ-1",
        ac_ids=["AC-1"],
    )


def _drafts(*names: str, changed: set[str] | None = None) -> TestCaseDesignSession:
    session = TestCaseDesignSession(story_key="PROJ-1", story_content="Story content", acceptance_criteria=_CRITERIA)
    for name in names:
        session.add_draft(_test_case(name))
    if changed is not None:
        session.changed_test_case_ids = changed
    return session


def _reviewed(*names: str) -> TestCaseDesignSession:
    session = _drafts(*names, changed=set())
    session.findings = {test_case_id: [] for test_case_id in session.test_cases}
    return session


def _finding(
    owner: str | None,
    action: FindingAction = FindingAction.MODIFY,
    related: list[str] | None = None,
    ac_ref: str | None = None,
) -> ReviewFinding:
    return ReviewFinding(
        owner_test_case_id=owner,
        action=action,
        severity=FindingSeverity.HIGH,
        category="coverage",
        description="A problem",
        suggested_fix="A fix",
        ac_ref=ac_ref,
        related_test_case_ids=related or [],
    )


def _feedback_runs(count: int, findings: list[ReviewFinding] | None = None) -> AsyncMock:
    return AsyncMock(
        side_effect=[
            MagicMock(output=TestCaseReviewFeedback(test_case_id="any", findings=findings or [])) for _ in range(count)
        ]
    )


def _hit(test_case_key: str, text: str = "candidate text") -> SimpleNamespace:
    return SimpleNamespace(payload={"test_case_key": test_case_key, "text": text})


def _judgement(*keys: str) -> MagicMock:
    overlaps = [
        OverlappingTestCase(test_case_key=key, overlap_explanation=f"Same as {key}", fully_covers=False) for key in keys
    ]
    return MagicMock(output=TestCaseDuplicateJudgement(overlapping_test_cases=overlaps))


async def test_review_covers_only_the_changed_drafts_as_compact_text_after_the_story_context(
    reviewer, download, caplog
):
    session = _drafts("First", "Second", "Third", changed={"DRAFT-2"})
    output = TestCaseReviewFeedback(test_case_id="DRAFT-2", findings=[], llm_comments="An attachment was unreadable")
    reviewer.review_agent.run = AsyncMock(return_value=MagicMock(output=output))

    with caplog.at_level(logging.WARNING, logger="test_case_review_agent"):
        await reviewer.review_changed(session, RunUsage(), _USAGE_LIMITS)

    assert "Review of test case 'DRAFT-2' reported: An attachment was unreadable" in caplog.text
    assert reviewer.review_agent.run.await_count == 1
    review = reviewer.review_agent.run.await_args
    message = review.args[0]
    assert message[0] == "Jira Issue content:\n```Story content```"
    assert message[1].startswith("Acceptance criteria:\n```") and '"id":"AC-2"' in message[1]
    assert len(message) == 3, "A new test case gets no previous-review part"
    assert message[2].startswith("Test case under review (ID DRAFT-2):\n```Name: Second\n")
    assert message[2].endswith("Acceptance criteria: AC-1```")
    assert '"summary"' not in message[2]
    assert not any("First" in part or "Third" in part for part in message if isinstance(part, str)), message
    assert review.kwargs["deps"] is session
    assert session.findings == {"DRAFT-2": []}
    assert session.changed_test_case_ids == set()


async def test_a_fixed_test_case_is_verified_against_its_previous_review_which_is_then_consumed(reviewer, download):
    session = _drafts("First fixed", "Second")
    previous_finding = _finding("DRAFT-1", ac_ref="AC-1")
    session.previous_reviews = {"DRAFT-1": PreviousReview(test_case=_test_case("First"), findings=[previous_finding])}
    reviewer.review_agent.run = _feedback_runs(2)

    await reviewer.review_changed(session, RunUsage(), _USAGE_LIMITS)

    messages = {call.args[0][2]: call.args[0] for call in reviewer.review_agent.run.await_args_list}
    fixed = next(message for part, message in messages.items() if "(ID DRAFT-1)" in part)
    new = next(message for part, message in messages.items() if "(ID DRAFT-2)" in part)
    assert fixed[3].startswith("Previous version of the test case under review:\n```Name: First\n")
    assert fixed[4] == f"Findings of the review of the previous version:\n```[{previous_finding.model_dump_json()}]```"
    assert len(new) == 3
    assert session.previous_reviews == {}


async def test_the_first_review_runs_alone_and_the_others_concurrently(reviewer, download):
    session = _drafts("First", "Second", "Third")
    events: list[str] = []
    others_started = asyncio.Event()

    async def review(message: list, **kwargs) -> MagicMock:
        test_case_id = message[2].split("(ID ")[1].split(")")[0]
        events.append(f"start {test_case_id}")
        if test_case_id != "DRAFT-1":
            if events.count("start DRAFT-2") + events.count("start DRAFT-3") == 2:
                others_started.set()
            await asyncio.wait_for(others_started.wait(), timeout=1)
        events.append(f"end {test_case_id}")
        return MagicMock(output=TestCaseReviewFeedback(test_case_id=test_case_id, findings=[]))

    reviewer.review_agent.run = review

    await reviewer.review_changed(session, RunUsage(), _USAGE_LIMITS)

    assert events[:2] == ["start DRAFT-1", "end DRAFT-1"]
    assert set(events[2:4]) == {"start DRAFT-2", "start DRAFT-3"}
    assert set(session.findings) == {"DRAFT-1", "DRAFT-2", "DRAFT-3"}


async def test_attachments_are_downloaded_once_per_session(reviewer, download):
    session = _drafts("First")
    reviewer.review_agent.run = _feedback_runs(2)

    await reviewer.review_changed(session, RunUsage(), _USAGE_LIMITS)
    session.changed_test_case_ids = {"DRAFT-1"}
    await reviewer.review_changed(session, RunUsage(), _USAGE_LIMITS)

    download.assert_called_once_with("PROJ-1")


async def test_sub_agent_runs_share_the_given_usage_and_limits(reviewer, download):
    session = _drafts("First", "Second")
    reviewer.review_agent.run = _feedback_runs(2)
    reviewer.vector_db_service.hybrid_search.return_value = [_hit("PROJ-T9")]
    reviewer.duplicate_judge.run.return_value = _judgement()
    usage = RunUsage()

    await reviewer.review_changed(session, usage, _USAGE_LIMITS)
    await reviewer.check_duplicates(session, usage, _USAGE_LIMITS)

    calls = reviewer.review_agent.run.await_args_list + reviewer.duplicate_judge.run.await_args_list
    assert reviewer.duplicate_judge.run.await_count == 2
    for call in calls:
        assert call.kwargs["usage"] is usage
        assert call.kwargs["usage_limits"] is _USAGE_LIMITS


async def test_a_single_review_keeps_only_its_own_modifications(reviewer, download):
    session = _drafts("First", "Second", changed={"DRAFT-1"})
    findings = [
        _finding("DRAFT-2", related=["DRAFT-2", "PROJ-T404", "DRAFT-1"]),
        _finding("DRAFT-1", FindingAction.DELETE_TEST_CASE),
        _finding(None, FindingAction.ADD_TEST_CASE),
        _finding("DRAFT-1", FindingAction.REMOVE_DUPLICATE_STEPS, related=["DRAFT-2"]),
    ]
    reviewer.review_agent.run = _feedback_runs(1, findings)

    await reviewer.review_changed(session, RunUsage(), _USAGE_LIMITS)

    owned = session.findings["DRAFT-1"]
    assert [finding.action for finding in owned] == [FindingAction.MODIFY]
    assert owned[0].owner_test_case_id == "DRAFT-1"
    assert owned[0].related_test_case_ids == []


def test_a_single_review_naming_an_unknown_criterion_is_rejected():
    ctx = SimpleNamespace(deps=_drafts("First"))
    known = TestCaseReviewFeedback(test_case_id="DRAFT-1", findings=[_finding("DRAFT-1", ac_ref="AC-2"), _finding("X")])

    assert review_main._validate_test_case_review(ctx, known) is known
    with pytest.raises(ModelRetry, match=r"Unknown acceptance criteria IDs \['AC-9'\] in `ac_ref`; use only"):
        review_main._validate_test_case_review(
            ctx, TestCaseReviewFeedback(test_case_id="DRAFT-1", findings=[_finding("DRAFT-1", ac_ref="AC-9")])
        )


async def test_the_reviewer_is_asked_again_when_a_finding_names_an_unknown_criterion(reviewer):
    answers = [
        TestCaseReviewFeedback(test_case_id="DRAFT-1", findings=[_finding("DRAFT-1", ac_ref=ac_ref)])
        for ac_ref in ("AC-9", "AC-2")
    ]

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, answers.pop(0).model_dump())])

    with reviewer.review_agent.override(model=FunctionModel(respond)):
        result = await reviewer.review_agent.run("Review", deps=_drafts("First"))

    assert result.output.findings[0].ac_ref == "AC-2"
    assert answers == []


async def test_closing_the_reviewer_closes_its_vector_db_client(reviewer):
    reviewer.vector_db_service.close = AsyncMock()

    await reviewer.close()

    reviewer.vector_db_service.close.assert_awaited_once()


async def test_a_review_round_runs_no_duplicate_check(reviewer, download):
    session = _drafts("First")
    reviewer.review_agent.run = _feedback_runs(1)

    await reviewer.review_changed(session, RunUsage(), _USAGE_LIMITS)

    reviewer.vector_db_service.hybrid_search.assert_not_awaited()
    assert session.duplicate_checks == {}


async def test_duplicate_check_searches_the_project_by_content_without_indexing(reviewer):
    await reviewer.check_duplicates(_reviewed("First"), RunUsage(), _USAGE_LIMITS)

    reviewer.vector_db_service.upsert_batch.assert_not_awaited()
    call = reviewer.vector_db_service.hybrid_search.await_args
    assert "Name: First" in call.args[0]
    assert call.kwargs["limit"] == 5
    assert call.kwargs["score_threshold"] == 0.8
    query_filter = call.kwargs["query_filter"]
    assert {(c.key, c.match.value) for c in query_filter.must} == {("source", "test_case"), ("project_key", "PROJ")}
    assert [(c.key, c.match.value) for c in query_filter.must_not] == [("test_case_key", "DRAFT-1")]


async def test_duplicate_check_covers_every_test_case_once(reviewer):
    session = _reviewed("First", "Second")

    await reviewer.check_duplicates(session, RunUsage(), _USAGE_LIMITS)

    assert reviewer.vector_db_service.hybrid_search.await_count == 2
    assert set(session.duplicate_checks) == {"DRAFT-1", "DRAFT-2"}


async def test_no_candidates_means_no_duplicates_without_asking_the_judge(reviewer):
    session = _reviewed("First")

    summary = await reviewer.check_duplicates(session, RunUsage(), _USAGE_LIMITS)

    reviewer.duplicate_judge.run.assert_not_awaited()
    assert summary == "DRAFT-1: no duplicates"
    assert session.duplicate_checks == {"DRAFT-1": TestCaseDuplicateCheck()}


async def test_candidates_are_deduplicated_by_key_before_judging(reviewer):
    session = _reviewed("First")
    reviewer.vector_db_service.hybrid_search.return_value = [
        _hit("PROJ-T7", "seven"),
        _hit("PROJ-T7", "seven again"),
        _hit("DRAFT-1", "itself"),
        _hit("PROJ-T8", "eight"),
    ]
    reviewer.duplicate_judge.run.return_value = _judgement("PROJ-T7", "PROJ-T404")

    summary = await reviewer.check_duplicates(session, RunUsage(), _USAGE_LIMITS)

    assert summary == "DRAFT-1: PROJ-T7"
    judge_message = reviewer.duplicate_judge.run.await_args.args[0]
    assert judge_message.count("Candidate PROJ-T7") == 1
    assert "Candidate PROJ-T8" in judge_message
    assert "Candidate DRAFT-1" not in judge_message
    expected = TestCaseDuplicateCheck(
        overlapping_test_cases=[
            OverlappingTestCase(test_case_key="PROJ-T7", overlap_explanation="Same as PROJ-T7", fully_covers=False)
        ]
    )
    assert session.duplicate_checks["DRAFT-1"] == expected


@pytest.mark.parametrize("stage", ["search", "judgement"])
async def test_duplicate_check_failure_fails_loudly(reviewer, caplog, stage):
    session = _reviewed("First")
    reviewer.vector_db_service.hybrid_search.return_value = [_hit("PROJ-T7")]
    failing = reviewer.vector_db_service.hybrid_search if stage == "search" else reviewer.duplicate_judge.run
    failing.side_effect = ConnectionError("down")

    with (
        caplog.at_level(logging.ERROR, logger="test_case_review_agent"),
        pytest.RaisesGroup(
            pytest.RaisesExc(
                TestCaseDuplicateCheckError, match=f"{stage} failed for test case\\(s\\) DRAFT-1 of project PROJ"
            )
        ),
    ):
        await reviewer.check_duplicates(session, RunUsage(), _USAGE_LIMITS)

    assert session.duplicate_checks == {}


async def test_a_failed_duplicate_check_leaves_no_verdict_of_the_other_test_cases(reviewer):
    session = _reviewed("First", "Second")

    async def search(text: str, **kwargs) -> list:
        if "Second" in text:
            raise ConnectionError("down")
        return []

    reviewer.vector_db_service.hybrid_search = search

    with pytest.RaisesGroup(pytest.RaisesExc(TestCaseDuplicateCheckError, match="DRAFT-2")):
        await reviewer.check_duplicates(session, RunUsage(), _USAGE_LIMITS)

    assert session.duplicate_checks == {}


async def test_the_duplicate_checks_of_the_test_cases_run_concurrently(reviewer):
    session = _reviewed("First", "Second")
    started: list[str] = []
    both_started = asyncio.Event()

    async def search(text: str, **kwargs) -> list:
        started.append(text)
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        return []

    reviewer.vector_db_service.hybrid_search = search

    summary = await reviewer.check_duplicates(session, RunUsage(), _USAGE_LIMITS)

    assert len(started) == 2
    assert summary == "DRAFT-1: no duplicates\nDRAFT-2: no duplicates"
    assert set(session.duplicate_checks) == {"DRAFT-1", "DRAFT-2"}


async def test_suite_review_sees_every_test_case_with_its_findings_after_the_story_context(reviewer, download):
    session = _reviewed("First", "Second")
    session.findings["DRAFT-1"] = [_finding("DRAFT-1")]
    gap = _finding(None, FindingAction.ADD_TEST_CASE)
    reviewer.test_suite_reviewer.run = AsyncMock(return_value=MagicMock(output=TestSuiteReview(findings=[gap])))
    usage = RunUsage()

    await reviewer.review_set(session, usage, _USAGE_LIMITS)

    call = reviewer.test_suite_reviewer.run.await_args
    message = call.args[0]
    assert message[0] == "Jira Issue content:\n```Story content```"
    assert message[1].startswith("Acceptance criteria:\n```")
    test_cases_part = message[2]
    assert "ID DRAFT-1:\n```Name: First\n" in test_cases_part
    assert "ID DRAFT-2:\n```Name: Second\n" in test_cases_part
    assert "Acceptance criteria: AC-1```" in test_cases_part
    assert '"owner_test_case_id":"DRAFT-1"' in test_cases_part
    assert call.kwargs["deps"] is session
    assert call.kwargs["usage"] is usage
    assert call.kwargs["usage_limits"] is _USAGE_LIMITS
    assert len(message) == 3, "Without deleted test cases there is no deleted-test-cases block"
    assert session.suite_findings == [gap]


async def test_suite_review_sees_each_deleted_test_case_with_the_finding_which_deleted_it(reviewer, download):
    session = _with_deleted("First")
    session.findings = {"DRAFT-1": []}
    reviewer.test_suite_reviewer.run = AsyncMock(return_value=MagicMock(output=TestSuiteReview(findings=[])))

    await reviewer.review_set(session, RunUsage(), _USAGE_LIMITS)

    message = reviewer.test_suite_reviewer.run.await_args.args[0]
    deleted_by = session.deleted_test_cases["DRAFT-9"].deleted_by.model_dump_json()
    assert message[3] == (
        "Deleted test cases:\nID DRAFT-9:\n"
        "```Name: Old\nObjective: Summary of Old\nPreconditions: \nAcceptance criteria: AC-1```\n"
        f"Finding which deleted it:\n```{deleted_by}```"
    )


def _with_deleted(*names: str) -> TestCaseDesignSession:
    session = _drafts(*names)
    deleted_by = _finding("DRAFT-9", FindingAction.DELETE_TEST_CASE, related=["DRAFT-1"])
    session.deleted_test_cases = {
        "DRAFT-9": DeletedTestCase(test_case=_test_case("Old"), findings=[], deleted_by=deleted_by)
    }
    return session


_DELETE = FindingAction.DELETE_TEST_CASE
_REMOVE_STEPS = FindingAction.REMOVE_DUPLICATE_STEPS


@pytest.mark.parametrize(
    ("findings", "error"),
    [
        ([_finding("DRAFT-8")], r"Unknown test case IDs \['DRAFT-8'\]"),
        ([_finding("DRAFT-9")], r"Unknown test case IDs \['DRAFT-9'\]"),
        ([_finding("DRAFT-1", related=["PROJ-T5"])], r"Unknown test case IDs \['PROJ-T5'\]"),
        ([_finding("DRAFT-1", FindingAction.ADD_TEST_CASE)], "has no owner test case"),
        ([_finding(None, _DELETE)], "needs exactly one owner test case"),
        (
            [_finding("DRAFT-1", _DELETE, related=["DRAFT-2"]), _finding("DRAFT-2", _DELETE)],
            r"'DRAFT-1' is deleted as covered by \['DRAFT-2'\], which are deleted too",
        ),
        (
            [_finding("DRAFT-1", _REMOVE_STEPS, related=["DRAFT-2"]), _finding("DRAFT-2", _DELETE)],
            r"finding of 'DRAFT-1' points at \['DRAFT-2'\], which is deleted",
        ),
        (
            [_finding("DRAFT-1", _DELETE), _finding("DRAFT-1", _REMOVE_STEPS, related=["DRAFT-2"])],
            r"finding of 'DRAFT-1' points at \['DRAFT-1'\], which is deleted",
        ),
        (
            [
                _finding("DRAFT-1", _REMOVE_STEPS, related=["DRAFT-2"]),
                _finding("DRAFT-2", _REMOVE_STEPS, related=["DRAFT-1"]),
            ],
            "'DRAFT-1' and 'DRAFT-2' remove their shared steps from each other",
        ),
        ([_finding(f"DRAFT-{n}", _DELETE) for n in (1, 2, 3)], "Every test case is deleted"),
        ([_finding("DRAFT-1", related=["DRAFT-9"])], r"deleted test cases \['DRAFT-9'\] may be named only by an"),
        ([_finding("DRAFT-1", ac_ref="AC-9")], r"Unknown acceptance criteria IDs \['AC-9'\] in `ac_ref`"),
    ],
    ids=[
        "unknown owner",
        "deleted owner",
        "unknown related",
        "owned addition",
        "ownerless deletion",
        "deletion covered by a deletion",
        "step removal against a deletion",
        "step removal of a deletion",
        "mutual step removal",
        "everything deleted",
        "deleted test case named by a modification",
        "unknown ac_ref",
    ],
)
def test_suite_review_output_with_unusable_findings_is_rejected(findings, error):
    ctx = SimpleNamespace(deps=_with_deleted("First", "Second", "Third"))

    with pytest.raises(ModelRetry, match=error):
        review_main._validate_test_suite_review(ctx, TestSuiteReview(findings=findings))


def test_a_mutual_step_removal_is_reported_once_and_a_self_reference_not_at_all():
    findings = [
        _finding("DRAFT-2", _REMOVE_STEPS, related=["DRAFT-1"]),
        _finding("DRAFT-1", _REMOVE_STEPS, related=["DRAFT-2"]),
        _finding("DRAFT-3", _REMOVE_STEPS, related=["DRAFT-3"]),
    ]

    assert review_main._set_errors(findings, _drafts("First", "Second", "Third")) == [
        "'DRAFT-1' and 'DRAFT-2' remove their shared steps from each other; remove them from one only."
    ]


def test_suite_review_output_with_a_merge_and_a_restore_passes():
    ctx = SimpleNamespace(deps=_with_deleted("First", "Second", "Third"))
    output = TestSuiteReview(
        findings=[
            _finding("DRAFT-1", _DELETE, related=["DRAFT-2"]),
            _finding("DRAFT-2", related=["DRAFT-1"], ac_ref="AC-1"),
            _finding(None, FindingAction.ADD_TEST_CASE, related=["DRAFT-9"], ac_ref="AC-2"),
        ]
    )

    assert review_main._validate_test_suite_review(ctx, output) is output


def test_the_smoke_rubric_override_differs_from_the_bundled_rubric_only_in_its_forced_finding():
    repo_root = Path(__file__).resolve().parents[2]
    rubric = Path("agents/test_case_review/system_prompts/severity_rubric.md")
    bundled = (repo_root / rubric).read_text(encoding="utf-8").splitlines()
    override = (repo_root / "tests/smoke/overrides" / rubric).read_text(encoding="utf-8").splitlines()

    assert len(override) == len(bundled), "The smoke override must track every line of the bundled rubric"
    differing = [line for line, bundled_line in zip(override, bundled, strict=True) if line != bundled_line]
    assert len(differing) == 1, differing
    assert "report at least one finding with the severity `high`" in differing[0]


def test_suite_review_output_with_usable_findings_passes():
    ctx = SimpleNamespace(deps=_drafts("First", "Second"))
    output = TestSuiteReview(
        findings=[
            _finding("DRAFT-1", FindingAction.REMOVE_DUPLICATE_STEPS, related=["DRAFT-2"]),
            _finding(None, FindingAction.ADD_TEST_CASE),
        ]
    )

    assert review_main._validate_test_suite_review(ctx, output) is output

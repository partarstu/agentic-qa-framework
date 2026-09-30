# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import logging
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RunUsage

from agents.test_case_review import main as review_main
from agents.test_case_review.main import TestCaseDuplicateCheckError, TestCaseReviewAgent
from common.models import (
    FindingAction,
    FindingSeverity,
    OverlappingTestCase,
    ReviewFinding,
    TestCase,
    TestCaseDesignSession,
    TestCaseDuplicateCheck,
    TestCaseDuplicateJudgement,
    TestCaseReviewFeedback,
    TestSuiteReview,
)


@pytest.fixture
def mock_config() -> Iterator[MagicMock]:
    with patch("agents.test_case_review.main.config") as mock_conf:
        mock_conf.TestCaseReviewAgentConfig.OWN_NAME = "review_agent"
        mock_conf.AGENT_BASE_URL = "http://localhost"
        mock_conf.TestCaseReviewAgentConfig.PORT = 8003
        mock_conf.TestCaseReviewAgentConfig.EXTERNAL_PORT = 8003
        mock_conf.TestCaseReviewAgentConfig.PROTOCOL = "http"
        mock_conf.TestCaseReviewAgentConfig.MODEL_NAME = "test"
        mock_conf.TestCaseReviewAgentConfig.VERSION = "2.5"
        mock_conf.TestCaseReviewAgentConfig.SKILL_ID = "test-case-review"
        mock_conf.TestCaseReviewAgentConfig.SKILL_NAME = "Test Case Review"
        mock_conf.TestCaseReviewAgentConfig.SKILL_DESCRIPTION = "Reviews test cases"
        mock_conf.TestCaseReviewAgentConfig.THINKING_LEVEL = "LOW"
        mock_conf.TestCaseReviewAgentConfig.MAX_REQUESTS_PER_TASK = 8
        mock_conf.TestCaseReviewAgentConfig.MAX_OUTPUT_TOKENS = None
        mock_conf.QdrantConfig.TEST_CASES_COLLECTION_NAME = "test_cases"
        mock_conf.QdrantConfig.TEST_CASE_DUPLICATE_MAX_CANDIDATES = 5
        mock_conf.QdrantConfig.TEST_CASE_DUPLICATE_MIN_SCORE = 0.8
        mock_conf.ATLASSIAN_MCP_SERVER_URL = "http://jira-mcp"
        mock_conf.MCP_SERVER_TIMEOUT_SECONDS = 30
        yield mock_conf


@pytest.fixture
def agent(mock_config: MagicMock) -> TestCaseReviewAgent:
    review_agent = TestCaseReviewAgent()
    review_agent.vector_db_service = MagicMock()
    review_agent.vector_db_service.upsert_batch = AsyncMock()
    review_agent.vector_db_service.hybrid_search = AsyncMock(return_value=[])
    review_agent.duplicate_judge.run = AsyncMock()
    return review_agent


@pytest.fixture
def download() -> Iterator[MagicMock]:
    with patch("common.services.jira_attachments.download_issue_attachments", return_value={}) as mock_download:
        yield mock_download


def _test_case(name: str) -> TestCase:
    return TestCase(
        key=None,
        name=name,
        summary=f"Summary of {name}",
        steps=[],
        labels=[],
        comment="",
        preconditions="",
        parent_issue_key="PROJ-1",
    )


def _drafts(*names: str, changed: set[str] | None = None) -> TestCaseDesignSession:
    session = TestCaseDesignSession(story_key="PROJ-1", story_content="Story content")
    for name in names:
        session.add_draft(_test_case(name))
    if changed is not None:
        session.changed_test_case_ids = changed
    return session


def _reviewed(*names: str) -> TestCaseDesignSession:
    session = _drafts(*names, changed=set())
    session.findings = {test_case_id: [] for test_case_id in session.test_cases}
    return session


def _ctx(session: TestCaseDesignSession) -> SimpleNamespace:
    return SimpleNamespace(deps=session, usage=RunUsage())


def _finding(
    owner: str | None,
    action: FindingAction = FindingAction.MODIFY,
    related: list[str] | None = None,
) -> ReviewFinding:
    return ReviewFinding(
        owner_test_case_id=owner,
        action=action,
        severity=FindingSeverity.HIGH,
        category="coverage",
        description="A problem",
        suggested_fix="A fix",
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
    overlaps = [OverlappingTestCase(test_case_key=key, overlap_explanation=f"Same as {key}") for key in keys]
    return MagicMock(output=TestCaseDuplicateJudgement(overlapping_test_cases=overlaps))


def test_agent_init(agent):
    assert agent.agent_name == "review_agent"
    assert agent.get_thinking_level() == "LOW"
    assert agent.get_max_requests_per_task() == 8


def _offering_model(offered: list[set[str]], instructions: list[str]) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        offered.append({tool.name for tool in info.function_tools})
        instructions.append(info.instructions or "")
        return ModelResponse(parts=[TextPart("done")])

    return FunctionModel(respond)


async def test_a_delegated_review_is_offered_only_the_two_reviews_and_no_jira_session(agent):
    offered: list[set[str]] = []
    instructions: list[str] = []

    with agent.agent.override(model=_offering_model(offered, instructions)):
        assert await agent.run_delegated("Review", _drafts("First"), RunUsage()) == "done"

    assert agent.mcp_toolset_factories == []
    assert offered[0] == {"review_test_cases", "review_test_suite", "report_activity"}
    assert "never fetch the Jira issue" in instructions[0]


async def test_designing_review_covers_only_the_changed_drafts(agent, download, caplog):
    session = _drafts("First", "Second", "Third", changed={"DRAFT-2"})
    output = TestCaseReviewFeedback(test_case_id="DRAFT-2", findings=[], llm_comments="An attachment was unreadable")
    agent.review_agent.run = AsyncMock(return_value=MagicMock(output=output))

    with caplog.at_level(logging.WARNING, logger="test_case_review_agent"):
        feedbacks = await agent.review_test_cases(_ctx(session))

    assert "Review of test case 'DRAFT-2' reported: An attachment was unreadable" in caplog.text
    assert agent.review_agent.run.await_count == 1
    message = agent.review_agent.run.await_args.args[0]
    assert message[0] == "Jira Issue content:\n```Story content```"
    assert "(ID DRAFT-2)" in message[1]
    assert "Summary of Second" in message[1]
    assert not any("First" in part or "Third" in part for part in message if isinstance(part, str)), message
    assert [feedback.test_case_id for feedback in feedbacks.review_feedbacks] == ["DRAFT-2"]
    assert session.findings == {"DRAFT-2": []}
    assert session.changed_test_case_ids == set()


async def test_attachments_are_downloaded_once_per_session(agent, download):
    session = _drafts("First")
    agent.review_agent.run = _feedback_runs(2)

    await agent.review_test_cases(_ctx(session))
    session.changed_test_case_ids = {"DRAFT-1"}
    await agent.review_test_cases(_ctx(session))

    download.assert_called_once_with("PROJ-1")


async def test_sub_agent_runs_share_the_task_usage_within_its_token_budget(agent, mock_config, download):
    session = _drafts("First", "Second")
    agent.review_agent.run = _feedback_runs(2)
    agent.vector_db_service.hybrid_search.return_value = [_hit("PROJ-T9")]
    agent.duplicate_judge.run.return_value = _judgement()
    ctx = _ctx(session)

    await agent.review_test_cases(ctx)
    await agent.check_duplicates(session, ctx.usage)

    calls = agent.review_agent.run.await_args_list + agent.duplicate_judge.run.await_args_list
    assert agent.duplicate_judge.run.await_count == 2
    assert all(call.kwargs["usage"] is ctx.usage for call in calls)
    for call in calls:
        assert call.kwargs["usage_limits"] == agent.get_sub_agent_usage_limits()
        assert call.kwargs["usage_limits"].tool_calls_limit is None


async def test_a_single_review_keeps_only_its_own_findings_and_leaves_the_whole_set_ones_out(agent, download):
    session = _drafts("First", "Second", changed={"DRAFT-1"})
    findings = [
        _finding("DRAFT-2", related=["DRAFT-2", "PROJ-T404", "DRAFT-1"]),
        _finding("DRAFT-1", FindingAction.DELETE_TEST_CASE),
        _finding(None, FindingAction.ADD_TEST_CASE),
        _finding("DRAFT-1", FindingAction.REMOVE_DUPLICATE_STEPS, related=["DRAFT-2"]),
    ]
    agent.review_agent.run = _feedback_runs(1, findings)

    await agent.review_test_cases(_ctx(session))

    owned = session.findings["DRAFT-1"]
    assert [finding.action for finding in owned] == [FindingAction.MODIFY, FindingAction.DELETE_TEST_CASE]
    assert all(finding.owner_test_case_id == "DRAFT-1" for finding in owned)
    assert all(finding.related_test_case_ids == [] for finding in owned)


async def test_a_review_round_runs_no_duplicate_check(agent, download):
    session = _drafts("First")
    agent.review_agent.run = _feedback_runs(1)

    await agent.review_test_cases(_ctx(session))

    agent.vector_db_service.hybrid_search.assert_not_awaited()
    assert session.duplicate_checks == {}


async def test_duplicate_check_searches_the_project_by_content_without_indexing(agent):
    await agent.check_duplicates(_reviewed("First"), RunUsage())

    agent.vector_db_service.upsert_batch.assert_not_awaited()
    call = agent.vector_db_service.hybrid_search.await_args
    assert "Name: First" in call.args[0]
    assert call.kwargs["limit"] == 5
    assert call.kwargs["score_threshold"] == 0.8
    query_filter = call.kwargs["query_filter"]
    assert {(c.key, c.match.value) for c in query_filter.must} == {("source", "test_case"), ("project_key", "PROJ")}
    assert [(c.key, c.match.value) for c in query_filter.must_not] == [("test_case_key", "DRAFT-1")]


async def test_duplicate_check_covers_every_test_case_once(agent):
    session = _reviewed("First", "Second")

    await agent.check_duplicates(session, RunUsage())

    assert agent.vector_db_service.hybrid_search.await_count == 2
    assert set(session.duplicate_checks) == {"DRAFT-1", "DRAFT-2"}


async def test_no_candidates_means_no_duplicates_without_asking_the_judge(agent):
    session = _reviewed("First")

    summary = await agent.check_duplicates(session, RunUsage())

    agent.duplicate_judge.run.assert_not_awaited()
    assert summary == "DRAFT-1: no duplicates"
    assert session.duplicate_checks == {"DRAFT-1": TestCaseDuplicateCheck()}


async def test_candidates_are_deduplicated_by_key_before_judging(agent):
    session = _reviewed("First")
    agent.vector_db_service.hybrid_search.return_value = [
        _hit("PROJ-T7", "seven"),
        _hit("PROJ-T7", "seven again"),
        _hit("DRAFT-1", "itself"),
        _hit("PROJ-T8", "eight"),
    ]
    agent.duplicate_judge.run.return_value = _judgement("PROJ-T7", "PROJ-T404")

    summary = await agent.check_duplicates(session, RunUsage())

    assert summary == "DRAFT-1: PROJ-T7"
    judge_message = agent.duplicate_judge.run.await_args.args[0]
    assert judge_message.count("Candidate PROJ-T7") == 1
    assert "Candidate PROJ-T8" in judge_message
    assert "Candidate DRAFT-1" not in judge_message
    expected = TestCaseDuplicateCheck(
        overlapping_test_cases=[OverlappingTestCase(test_case_key="PROJ-T7", overlap_explanation="Same as PROJ-T7")]
    )
    assert session.duplicate_checks["DRAFT-1"] == expected


@pytest.mark.parametrize("stage", ["search", "judgement"])
async def test_duplicate_check_failure_fails_loudly(agent, caplog, stage):
    session = _reviewed("First")
    agent.vector_db_service.hybrid_search.return_value = [_hit("PROJ-T7")]
    failing = agent.vector_db_service.hybrid_search if stage == "search" else agent.duplicate_judge.run
    failing.side_effect = ConnectionError("down")

    with (
        caplog.at_level(logging.ERROR, logger="test_case_review_agent"),
        pytest.raises(
            TestCaseDuplicateCheckError, match=f"{stage} failed for test case\\(s\\) DRAFT-1 of project PROJ"
        ),
    ):
        await agent.check_duplicates(session, RunUsage())

    assert session.duplicate_checks == {}


async def test_suite_review_runs_after_every_test_case_was_reviewed(agent, download):
    session = _drafts("First", "Second")
    agent.test_suite_reviewer.run = AsyncMock()

    with pytest.raises(ModelRetry, match="review tool first"):
        await agent.review_test_suite(_ctx(session))

    agent.test_suite_reviewer.run.assert_not_awaited()


async def test_suite_review_sees_every_test_case_with_its_findings(agent, download):
    session = _reviewed("First", "Second")
    session.findings["DRAFT-1"] = [_finding("DRAFT-1")]
    gap = _finding(None, FindingAction.ADD_TEST_CASE)
    agent.test_suite_reviewer.run = AsyncMock(return_value=MagicMock(output=TestSuiteReview(findings=[gap])))
    ctx = _ctx(session)

    result = await agent.review_test_suite(ctx)

    call = agent.test_suite_reviewer.run.await_args
    test_cases_part = call.args[0][1]
    assert "ID DRAFT-1" in test_cases_part
    assert "ID DRAFT-2" in test_cases_part
    assert '"owner_test_case_id":"DRAFT-1"' in test_cases_part
    assert call.kwargs["deps"] is session
    assert call.kwargs["usage"] is ctx.usage
    assert session.suite_findings == [gap]
    assert session.suite_reviewed
    assert result.findings == [gap]


@pytest.mark.parametrize(
    ("finding", "error"),
    [
        (_finding("DRAFT-9"), "Unknown test case IDs \\['DRAFT-9'\\]"),
        (_finding("DRAFT-1", related=["PROJ-T5"]), "Unknown test case IDs \\['PROJ-T5'\\]"),
        (_finding("DRAFT-1", FindingAction.ADD_TEST_CASE), "has no owner test case"),
        (_finding(None, FindingAction.DELETE_TEST_CASE), "needs exactly one owner test case"),
    ],
)
def test_suite_review_output_with_unusable_findings_is_rejected(finding, error):
    ctx = SimpleNamespace(deps=_drafts("First", "Second"))

    with pytest.raises(ModelRetry, match=error):
        review_main._validate_test_suite_review(ctx, TestSuiteReview(findings=[finding]))


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

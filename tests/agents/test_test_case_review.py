# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import ModelRetry

from agents.test_case_review import main as review_main
from agents.test_case_review.main import (
    DUPLICATE_CHECK_HEADING,
    TestCaseDuplicateCheckError,
    TestCaseReviewAgent,
    render_duplicate_check,
)
from common.agent_base import AgentBase
from common.models import (
    OverlappingTestCase,
    TestCase,
    TestCaseDuplicateCheck,
    TestCaseDuplicateJudgement,
    TestCaseReviewFeedback,
    TestCaseReviewFeedbacks,
)
from common.services.test_management_base import TestManagementClientBase

PROJECT_KEY = "PROJ"


@pytest.fixture
def mock_config():
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
        mock_conf.TestCaseReviewAgentConfig.REVIEW_COMPLETE_STATUS_NAME = "Review Complete"
        mock_conf.QdrantConfig.TEST_CASES_COLLECTION_NAME = "test_cases"
        mock_conf.QdrantConfig.TEST_CASE_DUPLICATE_MAX_CANDIDATES = 5
        mock_conf.QdrantConfig.TEST_CASE_DUPLICATE_MIN_SCORE = 0.8
        mock_conf.ATLASSIAN_MCP_SERVER_URL = "http://jira-mcp"
        mock_conf.MCP_SERVER_TIMEOUT_SECONDS = 30
        mock_conf.BudgetConfig.TOTAL_TOKENS_LIMIT_PER_TASK = 500_000
        yield mock_conf


@pytest.fixture
def agent(mock_config):
    # Patch PromptBase.get_prompt to avoid file reading issues
    with patch("agents.test_case_review.prompt.TestCaseReviewSystemPrompt.get_prompt", return_value="Prompt"):
        review_agent = TestCaseReviewAgent()
    review_agent.vector_db_service = MagicMock()
    review_agent.vector_db_service.upsert_batch = AsyncMock()
    review_agent.vector_db_service.hybrid_search = AsyncMock(return_value=[])
    review_agent.duplicate_judge.run = AsyncMock()
    return review_agent


@pytest.fixture
def duplicate_checks():
    """The verdict store of a running review task, as the agent's run() sets it."""
    checks: dict[str, TestCaseDuplicateCheck] = {}
    token = review_main._duplicate_checks.set(checks)
    yield checks
    review_main._duplicate_checks.reset(token)


@pytest.fixture
def no_attachments():
    with patch("common.services.jira_attachments.download_issue_attachments", return_value={}):
        yield


def _test_case(key: str | None, name: str) -> TestCase:
    return TestCase(
        key=key,
        name=name,
        summary=f"Summary of {name}",
        steps=[],
        labels=[],
        comment="",
        preconditions="",
        parent_issue_key="STORY-1",
    )


def _feedback_runs(test_cases: list[TestCase]) -> AsyncMock:
    return AsyncMock(
        side_effect=[
            MagicMock(output=TestCaseReviewFeedback(test_case_id=tc.key, review_feedback=["Improve it"]))
            for tc in test_cases
        ]
    )


def _hit(test_case_key: str, text: str = "candidate text") -> SimpleNamespace:
    return SimpleNamespace(payload={"test_case_key": test_case_key, "text": text})


def _judgement(*keys: str) -> MagicMock:
    overlaps = [OverlappingTestCase(test_case_key=key, overlap_explanation=f"Same as {key}") for key in keys]
    return MagicMock(output=TestCaseDuplicateJudgement(overlapping_test_cases=overlaps))


def test_agent_init(agent, mock_config):
    assert agent.agent_name == "review_agent"
    assert agent.get_thinking_level() == "LOW"
    assert agent.get_max_requests_per_task() == 8


@patch("agents.test_case_review.main.get_test_management_client")
async def test_add_review_feedback_appends_the_duplicate_check_to_the_comment(mock_get_client, agent, duplicate_checks):
    mock_client = MagicMock(spec=TestManagementClientBase)
    mock_get_client.return_value = mock_client
    duplicate_checks["TEST-1"] = TestCaseDuplicateCheck()

    result = await agent.add_review_feedback("TEST-1", "<ul><li>Feedback</li></ul>")

    mock_client.add_test_case_review_comment.assert_called_once_with(
        "TEST-1", f"<ul><li>Feedback</li></ul>\n{render_duplicate_check(TestCaseDuplicateCheck())}"
    )
    assert "Successfully added" in result


@patch("agents.test_case_review.main.get_test_management_client")
async def test_add_review_feedback_without_a_duplicate_check_is_an_error(mock_get_client, agent, duplicate_checks):
    with pytest.raises(ModelRetry, match="No duplicate check exists for the test case 'TEST-1'"):
        await agent.add_review_feedback("TEST-1", "Feedback")

    mock_get_client.return_value.add_test_case_review_comment.assert_not_called()


@patch("agents.test_case_review.main.get_test_management_client")
def test_set_test_case_status(mock_get_client, agent):
    mock_client = MagicMock(spec=TestManagementClientBase)
    mock_get_client.return_value = mock_client

    result = agent.set_test_case_status_to_review_complete("PROJ", "TEST-1")

    mock_client.change_test_case_status.assert_called_once_with("PROJ", "TEST-1", "Review Complete")
    assert "Successfully set status" in result


async def test_review_with_attachments_runs_once_per_test_case(agent, duplicate_checks, no_attachments):
    test_cases = [_test_case("TC-1", "First"), _test_case("TC-2", "Second"), _test_case("TC-3", "Third")]
    agent.review_agent.run = _feedback_runs(test_cases)

    feedbacks = await agent._review_test_cases_with_attachments(
        PROJECT_KEY, "STORY-1", "Jira issue content", test_cases
    )

    assert agent.review_agent.run.await_count == 3
    assert [feedback.test_case_id for feedback in feedbacks.review_feedbacks] == ["TC-1", "TC-2", "TC-3"]
    for call, test_case in zip(agent.review_agent.run.await_args_list, test_cases, strict=True):
        review_target = call.args[0][1]
        assert f"Summary of {test_case.name}" in review_target
        others = call.args[0][2]
        for other in test_cases:
            if other is not test_case:
                assert f"Summary of {other.name}" in others


async def test_review_with_attachments_shares_one_token_budget_across_the_runs(
    agent, mock_config, duplicate_checks, no_attachments
):
    """The sub-agent runs are outside the main run's budget, so they must carry their own."""
    test_cases = [_test_case("TC-1", "First"), _test_case("TC-2", "Second")]
    agent.review_agent.run = _feedback_runs(test_cases)
    agent.vector_db_service.hybrid_search.return_value = [_hit("TC-9")]
    agent.duplicate_judge.run.return_value = _judgement()

    await agent._review_test_cases_with_attachments(PROJECT_KEY, "STORY-1", "Jira issue content", test_cases)

    calls = agent.review_agent.run.await_args_list + agent.duplicate_judge.run.await_args_list
    usages = {id(call.kwargs["usage"]) for call in calls}
    assert len(usages) == 1, "All the runs must accumulate into the same usage, or the cap bounds none of them"
    for call in calls:
        assert call.kwargs["usage_limits"].total_tokens_limit == mock_config.BudgetConfig.TOTAL_TOKENS_LIMIT_PER_TASK


async def test_review_indexes_the_batch_under_review_before_reviewing(agent, duplicate_checks, no_attachments):
    test_cases = [_test_case("TC-1", "First"), _test_case("TC-2", "Second")]
    agent.review_agent.run = _feedback_runs(test_cases)

    await agent._review_test_cases_with_attachments(PROJECT_KEY, "STORY-1", "Jira issue content", test_cases)

    records = agent.vector_db_service.upsert_batch.await_args.args[0]
    assert [record.test_case_key for record in records] == ["TC-1", "TC-2"]
    assert {record.project_key for record in records} == {PROJECT_KEY}


async def test_review_rejects_a_test_case_without_a_key(agent, duplicate_checks, no_attachments):
    agent.review_agent.run = AsyncMock()

    with pytest.raises(ValueError, match="needs a key"):
        await agent._review_test_cases_with_attachments(
            PROJECT_KEY, "STORY-1", "content", [_test_case(None, "Keyless")]
        )

    agent.vector_db_service.upsert_batch.assert_not_awaited()
    agent.review_agent.run.assert_not_awaited()


async def test_review_rejects_a_blank_project_key(agent, duplicate_checks, no_attachments):
    with pytest.raises(ValueError, match="project_key must not be blank"):
        await agent._review_test_cases_with_attachments(" ", "STORY-1", "content", [_test_case("TC-1", "First")])


async def test_duplicate_search_is_scoped_to_the_project_and_excludes_the_test_case_itself(
    agent, duplicate_checks, no_attachments
):
    test_cases = [_test_case("TC-1", "First")]
    agent.review_agent.run = _feedback_runs(test_cases)

    await agent._review_test_cases_with_attachments(PROJECT_KEY, "STORY-1", "content", test_cases)

    call = agent.vector_db_service.hybrid_search.await_args
    assert "Name: First" in call.args[0]
    assert call.kwargs["limit"] == 5
    assert call.kwargs["score_threshold"] == 0.8
    query_filter = call.kwargs["query_filter"]
    assert {(c.key, c.match.value) for c in query_filter.must} == {("source", "test_case"), ("project_key", "PROJ")}
    assert [(c.key, c.match.value) for c in query_filter.must_not] == [("test_case_key", "TC-1")]


async def test_no_candidates_means_no_duplicates_without_asking_the_judge(agent, duplicate_checks, no_attachments):
    test_cases = [_test_case("TC-1", "First")]
    agent.review_agent.run = _feedback_runs(test_cases)

    feedbacks = await agent._review_test_cases_with_attachments(PROJECT_KEY, "STORY-1", "content", test_cases)

    agent.duplicate_judge.run.assert_not_awaited()
    assert feedbacks.review_feedbacks[0].duplicate_check == TestCaseDuplicateCheck()
    assert duplicate_checks == {"TC-1": TestCaseDuplicateCheck()}


async def test_candidates_are_deduplicated_by_key_before_judging(agent, duplicate_checks, no_attachments):
    test_cases = [_test_case("TC-1", "First")]
    agent.review_agent.run = _feedback_runs(test_cases)
    agent.vector_db_service.hybrid_search.return_value = [
        _hit("TC-7", "seven"),
        _hit("TC-7", "seven again"),
        _hit("TC-1", "itself"),
        _hit("TC-8", "eight"),
    ]
    agent.duplicate_judge.run.return_value = _judgement("TC-7")

    feedbacks = await agent._review_test_cases_with_attachments(PROJECT_KEY, "STORY-1", "content", test_cases)

    judge_message = agent.duplicate_judge.run.await_args.args[0]
    assert judge_message.count("Candidate TC-7") == 1
    assert "Candidate TC-8" in judge_message
    assert "Candidate TC-1" not in judge_message
    expected = TestCaseDuplicateCheck(
        overlapping_test_cases=[OverlappingTestCase(test_case_key="TC-7", overlap_explanation="Same as TC-7")]
    )
    assert feedbacks.review_feedbacks[0].duplicate_check == expected
    assert duplicate_checks["TC-1"] == expected


async def test_judge_verdicts_about_unknown_keys_are_dropped(agent, duplicate_checks, no_attachments):
    test_cases = [_test_case("TC-1", "First")]
    agent.review_agent.run = _feedback_runs(test_cases)
    agent.vector_db_service.hybrid_search.return_value = [_hit("TC-7")]
    agent.duplicate_judge.run.return_value = _judgement("TC-7", "TC-404")

    feedbacks = await agent._review_test_cases_with_attachments(PROJECT_KEY, "STORY-1", "content", test_cases)

    check = feedbacks.review_feedbacks[0].duplicate_check
    assert [overlap.test_case_key for overlap in check.overlapping_test_cases] == ["TC-7"]


async def test_indexing_failure_aborts_the_review(agent, duplicate_checks, no_attachments, caplog):
    agent.review_agent.run = AsyncMock()
    agent.vector_db_service.upsert_batch.side_effect = ConnectionError("qdrant down")

    with (
        caplog.at_level(logging.ERROR, logger="test_case_review_agent"),
        pytest.raises(TestCaseDuplicateCheckError, match="indexing failed for test case\\(s\\) TC-1 of project PROJ"),
    ):
        await agent._review_test_cases_with_attachments(PROJECT_KEY, "STORY-1", "content", [_test_case("TC-1", "A")])

    agent.review_agent.run.assert_not_awaited()
    assert "TC-1" in caplog.text
    assert "PROJ" in caplog.text


async def test_search_failure_aborts_the_review(agent, duplicate_checks, no_attachments, caplog):
    test_cases = [_test_case("TC-1", "First")]
    agent.review_agent.run = _feedback_runs(test_cases)
    agent.vector_db_service.hybrid_search.side_effect = ConnectionError("embedding service down")

    with (
        caplog.at_level(logging.ERROR, logger="test_case_review_agent"),
        pytest.raises(TestCaseDuplicateCheckError, match="search failed for test case\\(s\\) TC-1 of project PROJ"),
    ):
        await agent._review_test_cases_with_attachments(PROJECT_KEY, "STORY-1", "content", test_cases)

    assert "Duplicate check search failed for test case(s) TC-1 of project PROJ" in caplog.text
    assert duplicate_checks == {}


async def test_judge_failure_aborts_the_review(agent, duplicate_checks, no_attachments):
    test_cases = [_test_case("TC-1", "First")]
    agent.review_agent.run = _feedback_runs(test_cases)
    agent.vector_db_service.hybrid_search.return_value = [_hit("TC-7")]
    agent.duplicate_judge.run.side_effect = RuntimeError("model unavailable")

    with pytest.raises(TestCaseDuplicateCheckError, match="judgement failed for test case\\(s\\) TC-1"):
        await agent._review_test_cases_with_attachments(PROJECT_KEY, "STORY-1", "content", test_cases)

    assert duplicate_checks == {}


async def test_review_outside_a_task_run_has_no_verdict_store(agent, no_attachments):
    with pytest.raises(RuntimeError, match="only available inside a review task run"):
        await agent._review_test_cases_with_attachments(PROJECT_KEY, "STORY-1", "content", [_test_case("TC-1", "A")])


async def test_run_provides_a_fresh_verdict_store_and_removes_it_afterwards(agent):
    stores = []

    async def fake_run(self, message):
        stores.append(review_main._duplicate_checks.get())
        return message

    with patch.object(AgentBase, "run", fake_run):
        await agent.run(MagicMock())

    assert stores == [{}]
    assert review_main._duplicate_checks.get() is None


def test_final_output_carries_the_verdicts_computed_in_code(duplicate_checks):
    overlap = OverlappingTestCase(test_case_key="TC-7", overlap_explanation="Same flow")
    duplicate_checks["TC-1"] = TestCaseDuplicateCheck(overlapping_test_cases=[overlap])
    output = TestCaseReviewFeedbacks(
        review_feedbacks=[
            TestCaseReviewFeedback(test_case_id="TC-1", review_feedback=["a"]),
            TestCaseReviewFeedback(test_case_id="TC-2", review_feedback=["b"]),
        ]
    )

    result = review_main._attach_duplicate_checks(output)

    assert result.review_feedbacks[0].duplicate_check.overlapping_test_cases == [overlap]
    assert result.review_feedbacks[1].duplicate_check is None


def test_rendered_check_without_duplicates_says_so():
    rendered = render_duplicate_check(TestCaseDuplicateCheck())

    assert rendered == f"<h4>{DUPLICATE_CHECK_HEADING}</h4><p>No duplicate test cases found.</p>"


def test_rendered_check_lists_every_overlap_escaped():
    check = TestCaseDuplicateCheck(
        overlapping_test_cases=[
            OverlappingTestCase(test_case_key="TC-7", overlap_explanation="Both check <script>login</script>"),
            OverlappingTestCase(test_case_key="TC-8", overlap_explanation="Same logout"),
        ]
    )

    rendered = render_duplicate_check(check)

    assert rendered.startswith(f"<h4>{DUPLICATE_CHECK_HEADING}</h4><p>This test case overlaps in coverage with:</p>")
    assert "<li><b>TC-7</b>: Both check &lt;script&gt;login&lt;/script&gt;</li>" in rendered
    assert "<li><b>TC-8</b>: Same logout</li>" in rendered

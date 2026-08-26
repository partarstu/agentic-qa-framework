# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.test_case_review.main import TestCaseReviewAgent
from common.models import TestCase, TestCaseReviewFeedback
from common.services.test_management_base import TestManagementClientBase


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
        mock_conf.TestCaseReviewAgentConfig.THINKING_LEVEL = "LOW"
        mock_conf.TestCaseReviewAgentConfig.MAX_REQUESTS_PER_TASK = 8
        mock_conf.TestCaseReviewAgentConfig.REVIEW_COMPLETE_STATUS_NAME = "Review Complete"
        mock_conf.JIRA_MCP_SERVER_URL = "http://jira-mcp"
        mock_conf.MCP_SERVER_TIMEOUT_SECONDS = 30
        mock_conf.BudgetConfig.TOTAL_TOKENS_LIMIT_PER_TASK = 500_000
        yield mock_conf


@pytest.fixture
def agent(mock_config):
    # Patch PromptBase.get_prompt to avoid file reading issues
    with patch("agents.test_case_review.prompt.TestCaseReviewSystemPrompt.get_prompt", return_value="Prompt"):
        return TestCaseReviewAgent()


def test_agent_init(agent, mock_config):
    assert agent.agent_name == "review_agent"
    assert agent.get_thinking_level() == "LOW"
    assert agent.get_max_requests_per_task() == 8


@patch("agents.test_case_review.main.get_test_management_client")
def test_add_review_feedback(mock_get_client, agent):
    mock_client = MagicMock(spec=TestManagementClientBase)
    mock_get_client.return_value = mock_client

    result = agent.add_review_feedback("TEST-1", "Feedback")

    mock_client.add_test_case_review_comment.assert_called_once_with("TEST-1", "Feedback")
    assert "Successfully added" in result


@patch("agents.test_case_review.main.get_test_management_client")
def test_set_test_case_status(mock_get_client, agent):
    mock_client = MagicMock(spec=TestManagementClientBase)
    mock_get_client.return_value = mock_client

    result = agent.set_test_case_status_to_review_complete("PROJ", "TEST-1")

    mock_client.change_test_case_status.assert_called_once_with("PROJ", "TEST-1", "Review Complete")
    assert "Successfully set status" in result


def _test_case(key: str, name: str) -> TestCase:
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


@pytest.mark.asyncio
async def test_review_with_attachments_runs_once_per_test_case(agent):
    test_cases = [_test_case("TC-1", "First"), _test_case("TC-2", "Second"), _test_case("TC-3", "Third")]
    agent.review_agent.run = AsyncMock(
        side_effect=[
            MagicMock(output=TestCaseReviewFeedback(test_case_id=tc.key, review_feedback=["Improve it"]))
            for tc in test_cases
        ]
    )

    with patch.object(agent, "_fetch_attachments", return_value={}):
        feedbacks = await agent._review_test_cases_with_attachments("Jira issue content", [], test_cases)

    assert agent.review_agent.run.await_count == 3
    assert [feedback.test_case_id for feedback in feedbacks.review_feedbacks] == ["TC-1", "TC-2", "TC-3"]
    for call, test_case in zip(agent.review_agent.run.await_args_list, test_cases, strict=True):
        review_target = call.args[0][1]
        assert f"Summary of {test_case.name}" in review_target
        others = call.args[0][2]
        for other in test_cases:
            if other is not test_case:
                assert f"Summary of {other.name}" in others


@pytest.mark.asyncio
async def test_review_with_attachments_shares_one_token_budget_across_the_runs(agent, mock_config):
    """The sub-agent runs are outside the main run's budget, so they must carry their own."""
    test_cases = [_test_case("TC-1", "First"), _test_case("TC-2", "Second")]
    agent.review_agent.run = AsyncMock(
        side_effect=[
            MagicMock(output=TestCaseReviewFeedback(test_case_id=tc.key, review_feedback=["Improve it"]))
            for tc in test_cases
        ]
    )

    with patch.object(agent, "_fetch_attachments", return_value={}):
        await agent._review_test_cases_with_attachments("Jira issue content", [], test_cases)

    usages = {id(call.kwargs["usage"]) for call in agent.review_agent.run.await_args_list}
    assert len(usages) == 1, "All the runs must accumulate into the same usage, or the cap bounds none of them"
    for call in agent.review_agent.run.await_args_list:
        assert call.kwargs["usage_limits"].total_tokens_limit == mock_config.BudgetConfig.TOTAL_TOKENS_LIMIT_PER_TASK

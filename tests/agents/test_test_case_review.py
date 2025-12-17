
import pytest
from unittest.mock import MagicMock, patch
import sys

# Mock MCPServerSSE before importing the module
with patch("pydantic_ai.mcp.MCPServerSSE"):
    from agents.test_case_review.main import TestCaseReviewAgent

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
        mock_conf.TestCaseReviewAgentConfig.THINKING_BUDGET = 1500
        mock_conf.TestCaseReviewAgentConfig.MAX_REQUESTS_PER_TASK = 8
        mock_conf.TestCaseReviewAgentConfig.REVIEW_COMPLETE_STATUS_NAME = "Review Complete"
        mock_conf.JIRA_MCP_SERVER_URL = "http://jira-mcp"
        mock_conf.MCP_SERVER_TIMEOUT_SECONDS = 30
        yield mock_conf

@pytest.fixture
def agent(mock_config):
    # Patch PromptBase.get_prompt to avoid file reading issues
    with patch("agents.test_case_review.prompt.TestCaseReviewSystemPrompt.get_prompt", return_value="Prompt"):
        return TestCaseReviewAgent()

def test_agent_init(agent, mock_config):
    assert agent.agent_name == "review_agent"
    assert agent.get_thinking_budget() == 1500
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

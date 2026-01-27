
import sys
from unittest.mock import MagicMock, patch

import pytest

# Mock MCPServerSSE before importing the module
with patch("pydantic_ai.mcp.MCPServerSSE"):
    from agents.test_case_classification.main import TestCaseClassificationAgent

from common.services.test_management_base import TestManagementClientBase


@pytest.fixture
def mock_config():
    with patch("agents.test_case_classification.main.config") as mock_conf:
        # Set config values required by AgentBase init
        mock_conf.TestCaseClassificationAgentConfig.OWN_NAME = "classification_agent"
        mock_conf.AGENT_BASE_URL = "http://localhost"
        mock_conf.TestCaseClassificationAgentConfig.PORT = 8001
        mock_conf.TestCaseClassificationAgentConfig.EXTERNAL_PORT = 8001
        mock_conf.TestCaseClassificationAgentConfig.PROTOCOL = "http"
        mock_conf.TestCaseClassificationAgentConfig.MODEL_NAME = "test"
        mock_conf.TestCaseClassificationAgentConfig.THINKING_BUDGET = 1000
        mock_conf.TestCaseClassificationAgentConfig.MAX_REQUESTS_PER_TASK = 5
        mock_conf.JIRA_MCP_SERVER_URL = "http://jira-mcp"
        mock_conf.MCP_SERVER_TIMEOUT_SECONDS = 30
        yield mock_conf

@pytest.fixture
def agent(mock_config):
    # Patch PromptBase.get_prompt to avoid file reading issues
    with patch("agents.test_case_classification.prompt.TestCaseClassificationSystemPrompt.get_prompt", return_value="Prompt"):
        return TestCaseClassificationAgent()

def test_agent_init(agent, mock_config):
    assert agent.agent_name == "classification_agent"
    assert agent.get_thinking_budget() == 1000
    assert agent.get_max_requests_per_task() == 5

@patch("agents.test_case_classification.main.get_test_management_client")
def test_add_labels_to_test_case(mock_get_client, agent):
    mock_client = MagicMock(spec=TestManagementClientBase)
    mock_get_client.return_value = mock_client

    result = agent.add_labels_to_test_case("TEST-1", ["L1", "L2"])

    mock_client.add_labels_to_test_case.assert_called_once_with("TEST-1", ["L1", "L2"])
    assert "Successfully added labels" in result


import pytest
from unittest.mock import patch, MagicMock
from agents.requirements_review.main import RequirementsReviewAgent
import config

@pytest.fixture
def mock_config(monkeypatch):
    monkeypatch.setattr(config.RequirementsReviewAgentConfig, "OWN_NAME", "Test Agent")
    monkeypatch.setattr(config.RequirementsReviewAgentConfig, "PORT", 8001)
    monkeypatch.setattr(config.RequirementsReviewAgentConfig, "EXTERNAL_PORT", 8001)
    monkeypatch.setattr(config.RequirementsReviewAgentConfig, "PROTOCOL", "http")
    monkeypatch.setattr(config.RequirementsReviewAgentConfig, "MODEL_NAME", "test-model")
    monkeypatch.setattr(config.RequirementsReviewAgentConfig, "THINKING_BUDGET", 100)
    monkeypatch.setattr(config.RequirementsReviewAgentConfig, "MAX_REQUESTS_PER_TASK", 5)
    monkeypatch.setattr(config, "AGENT_BASE_URL", "http://localhost")
    monkeypatch.setattr(config, "JIRA_MCP_SERVER_URL", "http://jira")
    monkeypatch.setattr(config, "MCP_SERVER_TIMEOUT_SECONDS", 30)

@patch("agents.requirements_review.main.RequirementsReviewSystemPrompt")
@patch("agents.requirements_review.main.AgentBase.__init__")
def test_requirements_review_agent_init(mock_super_init, mock_prompt_cls, mock_config):
    mock_prompt_instance = MagicMock()
    mock_prompt_instance.get_prompt.return_value = "system prompt"
    mock_prompt_cls.return_value = mock_prompt_instance
    
    agent = RequirementsReviewAgent()
    
    mock_super_init.assert_called_once()
    args, kwargs = mock_super_init.call_args
    assert kwargs["agent_name"] == "Test Agent"
    assert kwargs["instructions"] == "system prompt"
    
    assert agent.get_thinking_budget() == 100
    assert agent.get_max_requests_per_task() == 5

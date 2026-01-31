# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Example: Unit tests for an agent.

Replace <agent_name> with your agent's folder name (e.g., requirements_review).
Replace <AgentName> with your agent's class name (e.g., RequirementsReview).
"""

from unittest.mock import MagicMock, patch

import pytest

import config
from agents.<agent_name>.main import <AgentName>Agent


@pytest.fixture
def mock_config(monkeypatch):
    """Mock configuration values for testing."""
    monkeypatch.setattr(config.<AgentName>AgentConfig, "OWN_NAME", "Test Agent")
    monkeypatch.setattr(config.<AgentName>AgentConfig, "PORT", 8099)
    monkeypatch.setattr(config.<AgentName>AgentConfig, "EXTERNAL_PORT", 8099)
    monkeypatch.setattr(config.<AgentName>AgentConfig, "PROTOCOL", "http")
    monkeypatch.setattr(config.<AgentName>AgentConfig, "MODEL_NAME", "test")
    monkeypatch.setattr(config.<AgentName>AgentConfig, "THINKING_BUDGET", 100)
    monkeypatch.setattr(config.<AgentName>AgentConfig, "MAX_REQUESTS_PER_TASK", 5)
    monkeypatch.setattr(config, "AGENT_BASE_URL", "http://localhost")
    # Add any agent-specific config mocks here


@patch("agents.<agent_name>.main.<AgentName>SystemPrompt")
@patch("agents.<agent_name>.main.AgentBase.__init__")
def test_agent_init(mock_super_init, mock_prompt_cls, mock_config):
    """Test agent initializes with correct configuration."""
    mock_prompt_instance = MagicMock()
    mock_prompt_instance.get_prompt.return_value = "system prompt"
    mock_prompt_cls.return_value = mock_prompt_instance

    agent = <AgentName>Agent()

    mock_super_init.assert_called_once()
    _, kwargs = mock_super_init.call_args
    assert kwargs["agent_name"] == "Test Agent"
    assert kwargs["instructions"] == "system prompt"

    assert agent.get_thinking_budget() == 100
    assert agent.get_max_requests_per_task() == 5


# =============================================================================
# Testing Custom Agent Tools
# =============================================================================

@pytest.mark.asyncio
async def test_custom_tool_success(mock_config):
    """Test custom tool returns expected result."""
    with patch("agents.<agent_name>.main.AgentBase.__init__"):
        agent = <AgentName>Agent()
        
        # Mock any external dependencies the tool uses
        with patch("agents.<agent_name>.main.external_service") as mock_service:
            mock_service.call.return_value = "expected result"
            
            result = await agent.custom_tool("input")
            
            assert result == "expected result"
            mock_service.call.assert_called_once_with("input")


@pytest.mark.asyncio
async def test_custom_tool_handles_error(mock_config):
    """Test custom tool handles errors gracefully."""
    with patch("agents.<agent_name>.main.AgentBase.__init__"):
        agent = <AgentName>Agent()
        
        with patch("agents.<agent_name>.main.external_service") as mock_service:
            mock_service.call.side_effect = Exception("Service unavailable")
            
            with pytest.raises(RuntimeError):
                await agent.custom_tool("input")

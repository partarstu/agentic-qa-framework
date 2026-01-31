# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Unit test example for a new agent.

Replace <agent_name> with your agent's folder name (e.g., requirements_review).
Replace <AgentName> with your agent's class name (e.g., RequirementsReview).
"""

from unittest.mock import MagicMock, patch

import pytest

import config
from agents.<agent_name>.main import <AgentName>Agent


@pytest.fixture
def mock_config(monkeypatch):
    monkeypatch.setattr(config.<AgentName>AgentConfig, "OWN_NAME", "Test Agent")
    monkeypatch.setattr(config.<AgentName>AgentConfig, "PORT", 8099)
    monkeypatch.setattr(config.<AgentName>AgentConfig, "EXTERNAL_PORT", 8099)
    monkeypatch.setattr(config.<AgentName>AgentConfig, "PROTOCOL", "http")
    monkeypatch.setattr(config.<AgentName>AgentConfig, "MODEL_NAME", "test")
    monkeypatch.setattr(config.<AgentName>AgentConfig, "THINKING_BUDGET", 100)
    monkeypatch.setattr(config.<AgentName>AgentConfig, "MAX_REQUESTS_PER_TASK", 5)
    monkeypatch.setattr(config, "AGENT_BASE_URL", "http://localhost")


@patch("agents.<agent_name>.main.<AgentName>SystemPrompt")
@patch("agents.<agent_name>.main.AgentBase.__init__")
def test_agent_init(mock_super_init, mock_prompt_cls, mock_config):
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

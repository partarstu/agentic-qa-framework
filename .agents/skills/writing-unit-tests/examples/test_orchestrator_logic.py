# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Example: Unit tests for orchestrator logic functions.

These tests verify agent discovery, card fetching, and registry operations.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.types import AgentCapabilities, AgentCard

import config
from orchestrator.main import (
    AgentStatus,
    BrokenReason,
    _discover_agents,
    _fetch_agent_card,
    _select_agent,
    agent_registry,
    discovery_agent,
)


@pytest.fixture
async def clear_registry():
    """Clear agent registry before and after each test."""
    agent_registry._cards.clear()
    agent_registry._statuses.clear()
    agent_registry._broken_reasons.clear()
    agent_registry._stuck_task_ids.clear()
    yield
    agent_registry._cards.clear()
    agent_registry._statuses.clear()
    agent_registry._broken_reasons.clear()
    agent_registry._stuck_task_ids.clear()


@pytest.fixture
def mock_agent_card():
    """Create a mock AgentCard for testing."""
    return AgentCard(
        name="Test Agent",
        description="Test description",
        url="http://localhost:8001",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=[],
        defaultInputModes=['text'],
        defaultOutputModes=['text']
    )


@pytest.mark.asyncio
async def test_fetch_agent_card_success(mock_agent_card):
    """Test successful agent card fetch."""
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_agent_card.model_dump()
        mock_client.get.return_value = mock_response

        card = await _fetch_agent_card("http://localhost:8001")
        assert card.name == "Test Agent"


@pytest.mark.asyncio
async def test_fetch_agent_card_failure():
    """Test agent card fetch handles connection errors."""
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.get.side_effect = Exception("Connection error")

        card = await _fetch_agent_card("http://bad-url")
        assert card is None

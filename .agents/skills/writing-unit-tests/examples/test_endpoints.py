# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Example: Unit tests for orchestrator endpoints.

These tests use FastAPI TestClient to test HTTP endpoints.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from orchestrator.main import orchestrator_app


@pytest.fixture
def client():
    """Create test client for orchestrator."""
    return TestClient(orchestrator_app)


@pytest.fixture
def mock_api_key(monkeypatch):
    """Bypass API key validation."""
    monkeypatch.setattr("orchestrator.main._validate_api_key", lambda x=None: None)


@pytest.fixture
def mock_agent_registry():
    """Mock the agent registry."""
    with patch("orchestrator.main.agent_registry") as mock:
        mock.is_empty = AsyncMock(return_value=False)
        mock.get_all_cards = AsyncMock(return_value={"agent-1": MagicMock()})
        mock.get_status = AsyncMock(return_value="AVAILABLE")
        yield mock


class TestWorkflowEndpoints:
    """Tests for orchestrator workflow endpoints."""

    @pytest.mark.asyncio
    async def test_workflow_endpoint_success(self, client, mock_api_key):
        """Test successful workflow execution."""
        with patch("orchestrator.main._send_task_to_agent") as mock_send, \
             patch("orchestrator.main._get_artifacts_from_task") as mock_artifacts:
            
            mock_task = MagicMock()
            mock_task.status.state = "completed"
            mock_send.return_value = mock_task
            mock_artifacts.return_value = [...]  # Mock artifacts
            
            response = client.post(
                "/endpoint-path",
                json={"field": "value"}
            )
            
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_workflow_endpoint_agent_unavailable(self, client, mock_api_key):
        """Test workflow handles agent unavailability."""
        with patch("orchestrator.main._send_task_to_agent") as mock_send:
            mock_send.side_effect = Exception("No agents available")
            
            response = client.post(
                "/endpoint-path",
                json={"field": "value"}
            )
            
            assert response.status_code == 500

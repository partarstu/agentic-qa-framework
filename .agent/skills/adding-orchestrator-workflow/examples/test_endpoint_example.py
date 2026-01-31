# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Unit test examples for orchestrator endpoints.

Replace <workflow_name> and <endpoint-path> with your workflow's values.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from orchestrator.main import orchestrator_app


@pytest.fixture
def client():
    return TestClient(orchestrator_app)


@pytest.fixture
def mock_api_key(monkeypatch):
    """Allow requests without API key check."""
    monkeypatch.setattr("orchestrator.main._validate_api_key", lambda x=None: None)


@pytest.mark.asyncio
async def test_<workflow_name>_success(client, mock_api_key):
    with patch("orchestrator.main._send_task_to_agent") as mock_send:
        # Setup mock response
        mock_task = MagicMock()
        mock_task.status.state = "completed"
        mock_task.artifacts = [...]  # Mock artifacts
        mock_send.return_value = mock_task
        
        response = client.post(
            "/<endpoint-path>",
            json={"field_name": "value"}
        )
        
        assert response.status_code == 200
        assert "message" in response.json()


@pytest.mark.asyncio
async def test_<workflow_name>_agent_error(client, mock_api_key):
    with patch("orchestrator.main._send_task_to_agent") as mock_send:
        mock_send.side_effect = Exception("Agent unavailable")
        
        response = client.post(
            "/<endpoint-path>",
            json={"field_name": "value"}
        )
        
        assert response.status_code == 500

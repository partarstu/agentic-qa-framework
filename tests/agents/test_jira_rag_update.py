# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from agents.jira_rag_update.main import JiraRagUpdateAgent
from common.models import JiraIssue

@pytest.fixture
def mock_db_service():
    with patch("agents.jira_rag_update.main.VectorDbService") as MockService:
        mock_instance = MockService.return_value
        mock_instance.upsert = AsyncMock()
        mock_instance.delete = AsyncMock()
        mock_instance._ensure_collection = AsyncMock()
        mock_instance.client = AsyncMock()
        yield mock_instance

@pytest.fixture
def agent(mock_db_service):
    with patch("agents.jira_rag_update.main.jira_mcp_server"):
        return JiraRagUpdateAgent()

@pytest.mark.asyncio
async def test_upsert_issues(agent):
    issues = [
        {
            "key": "TEST-1",
            "id": "1001",
            "fields": {
                "summary": "Summary",
                "description": "Desc",
                "status": {"name": "To Do"},
                "issuetype": {"name": "Bug"}
            }
        }
    ]
    
    result = await agent.upsert_issues("TEST_PROJ", issues)
    
    assert "Upserted 1 issues" in result
    agent.issues_db.upsert.assert_called_once()
    
    # Verify arguments
    call_args = agent.issues_db.upsert.call_args
    # call_args.kwargs['data'] should be a JiraIssue
    jira_issue = call_args.kwargs['data']
    assert isinstance(jira_issue, JiraIssue)
    assert jira_issue.key == "TEST-1"
    assert jira_issue.issue_type == "Bug"
    assert jira_issue.project_key == "TEST_PROJ"

@pytest.mark.asyncio
async def test_delete_issues(agent):
    result = await agent.delete_issues(["TEST-1"])
    assert "Deleted 1 issues" in result
    agent.issues_db.delete.assert_called_once_with(["TEST-1"])

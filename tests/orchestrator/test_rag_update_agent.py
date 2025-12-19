import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from orchestrator.rag_update_agent import upsert_issues, delete_issues, RagUpdateDeps

@pytest.fixture
def mock_db():
    with patch("orchestrator.rag_update_agent.issues_db") as mock_issues, \
         patch("orchestrator.rag_update_agent.metadata_db") as mock_meta:
        mock_issues.upsert = AsyncMock()
        mock_issues.delete = AsyncMock()
        yield mock_issues, mock_meta

@pytest.mark.asyncio
async def test_upsert_issues(mock_db):
    mock_issues_db, _ = mock_db
    
    ctx = MagicMock()
    ctx.deps = RagUpdateDeps(project_key="TEST")
    
    issues = [
        {
            "key": "TEST-1",
            "fields": {
                "summary": "Summary",
                "description": "Desc",
                "status": {"name": "To Do"}
            }
        }
    ]
    
    result = await upsert_issues(ctx, issues)
    assert "Upserted 1 issues" in result
    mock_issues_db.upsert.assert_called_once()

@pytest.mark.asyncio
async def test_delete_issues(mock_db):
    mock_issues_db, _ = mock_db
    ctx = MagicMock()
    
    result = await delete_issues(ctx, ["TEST-1"])
    assert "Deleted 1 issues" in result
    mock_issues_db.delete.assert_called_once_with(["TEST-1"])


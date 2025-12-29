import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import sys

# Mock MCPServerSSE
with patch("pydantic_ai.mcp.MCPServerSSE"):
    from agents.incident_creation.main import IncidentCreationAgent

from common.models import IncidentCreationInput, IncidentCreationResult, DuplicateDetectionResult, TestCase
from a2a.types import FileWithBytes

@pytest.fixture
def mock_config():
    with patch("agents.incident_creation.main.config") as mock_conf:
        mock_conf.IncidentCreationAgentConfig.OWN_NAME = "incident_creation_agent"
        mock_conf.AGENT_BASE_URL = "http://localhost"
        mock_conf.IncidentCreationAgentConfig.PORT = 8005
        mock_conf.IncidentCreationAgentConfig.EXTERNAL_PORT = 8005
        mock_conf.IncidentCreationAgentConfig.PROTOCOL = "http"
        mock_conf.IncidentCreationAgentConfig.MODEL_NAME = "test"
        mock_conf.IncidentCreationAgentConfig.THINKING_BUDGET = 16000
        mock_conf.JIRA_MCP_SERVER_URL = "http://jira-mcp"
        mock_conf.MCP_SERVER_TIMEOUT_SECONDS = 30
        mock_conf.QdrantConfig.COLLECTION_NAME = "jira_issues"
        mock_conf.QdrantConfig.MIN_SIMILARITY_SCORE = 0.7
        mock_conf.QdrantConfig.MAX_RESULTS = 5
        yield mock_conf

@pytest.fixture
def agent(mock_config):
    with patch("agents.incident_creation.prompt.IncidentCreationPrompt.get_prompt", return_value="Prompt"), \
         patch("agents.incident_creation.prompt.DuplicateDetectionPrompt.get_prompt", return_value="Dup Prompt"), \
         patch("agents.incident_creation.main.Agent") as mock_agent_cls:
        
        mock_agent_cls.side_effect = lambda *args, **kwargs: MagicMock()
        
        agent_inst = IncidentCreationAgent()
        agent_inst.vector_db_service = AsyncMock() # Mock the vector DB service
        yield agent_inst

def test_agent_init(agent, mock_config):
    assert agent.agent_name == "incident_creation_agent"
    assert agent.get_thinking_budget() == 16000
    assert agent.duplicate_detector is not None

@pytest.mark.asyncio
async def test_search_duplicates_in_rag(agent):
    # Prepare input
    test_case = TestCase(
        key="TC-123",
        labels=[],
        name="Sample Test Case",
        summary="Test case for testing",
        comment="",
        preconditions=None,
        steps=[],
        parent_issue_key=None
    )
    input_data = IncidentCreationInput(
        test_case=test_case,
        test_execution_result="Failed with NPE",
        test_step_results=[],
        system_description="Win10"
    )
    
    # Create incident description
    incident_description = f"""Test Case: {input_data.test_case.key}
Error Description: {input_data.test_execution_result}
System: {input_data.system_description}"""
    
    # Mock Vector DB search
    mock_hit = MagicMock()
    mock_hit.payload = {"issue_key": "BUG-1", "content": "Similar NPE"}
    mock_hit.score = 0.85
    agent.vector_db_service.search.return_value = [mock_hit]
    
    # Run
    candidates = await agent._search_duplicate_candidates_in_rag(incident_description)
    
    assert len(candidates) == 1
    assert candidates[0]["issue_key"] == "BUG-1"
    assert candidates[0]["content"] == "Similar NPE"
    assert candidates[0]["similarity_score"] == 0.85
    
    agent.vector_db_service.search.assert_called_once()



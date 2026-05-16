import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock MCPServerSSE
with patch("pydantic_ai.mcp.MCPServerSSE"):
    from agents.incident_creation.main import IncidentCreationAgent

from common.models import (
    DuplicateCandidate,
    DuplicateDetectionResult,
    DuplicateIssue,
    IncidentCreationInput,
    IncidentCreationResult,
    TestCase,
)


@pytest.fixture
def mock_config():
    with patch("agents.incident_creation.main.config") as mock_conf:
        mock_conf.IncidentCreationAgentConfig.OWN_NAME = "incident_creation_agent"
        mock_conf.AGENT_BASE_URL = "http://localhost"
        mock_conf.IncidentCreationAgentConfig.PORT = 8005
        mock_conf.IncidentCreationAgentConfig.EXTERNAL_PORT = 8005
        mock_conf.IncidentCreationAgentConfig.PROTOCOL = "http"
        mock_conf.IncidentCreationAgentConfig.MODEL_NAME = "test"
        mock_conf.IncidentCreationAgentConfig.THINKING_LEVEL = "HIGH"
        mock_conf.JIRA_MCP_SERVER_URL = "http://jira-mcp"
        mock_conf.MCP_SERVER_TIMEOUT_SECONDS = 30
        mock_conf.QdrantConfig.COLLECTION_NAME = "jira_issues"
        mock_conf.QdrantConfig.MIN_SIMILARITY_SCORE = 0.7
        mock_conf.QdrantConfig.MAX_RESULTS = 5
        yield mock_conf


@pytest.fixture
def agent(mock_config):
    with (
        patch("agents.incident_creation.prompt.IncidentCreationPrompt.get_prompt", return_value="Prompt"),
        patch("agents.incident_creation.prompt.DuplicateDetectionPrompt.get_prompt", return_value="Dup Prompt"),
        patch("common.custom_llm_wrapper.CustomLlmWrapper.create_agent") as mock_create_agent,
        patch("common.agent_base.AgentBase._get_server", return_value=MagicMock()),
    ):
        mock_create_agent.side_effect = [MagicMock(), MagicMock()]

        agent_inst = IncidentCreationAgent()
        agent_inst.vector_db_service = AsyncMock()
        yield agent_inst


def test_agent_init(agent, mock_config):
    assert agent.agent_name == "incident_creation_agent"
    assert agent.get_thinking_level() == "HIGH"
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
        parent_issue_key=None,
    )
    input_data = IncidentCreationInput(
        test_case=test_case,
        test_execution_result="Failed with NPE",
        test_step_results=[],
        system_description="Win10",
        issue_priority_field_id="priority",
        issue_severity_field_name="Severity",
    )

    # Create incident description
    incident_description = f"""Test Case: {input_data.test_case.key}
Error Description: {input_data.test_execution_result}
System: {input_data.system_description}"""

    # Mock Vector DB search with a valid JiraIssue payload
    mock_hit = MagicMock()
    mock_hit.payload = {
        "id": 10001,
        "key": "BUG-1",
        "summary": "Similar NPE in login flow",
        "description": "Similar NPE",
        "issue_type": "Bug",
        "status": "Open",
        "project_key": "PROJ",
    }
    mock_hit.score = 0.85
    agent.vector_db_service.search.return_value = [mock_hit]

    # Run
    candidates = await agent._search_duplicate_candidates_in_rag(incident_description)

    assert len(candidates) == 1
    assert candidates[0].key == "BUG-1"
    assert candidates[0].description == "Similar NPE"
    assert candidates[0].issue_type == "Bug"

    agent.vector_db_service.search.assert_called_once()


@pytest.mark.asyncio
async def test_link_issue_to_test_case_tool(agent):
    with patch("agents.incident_creation.main.get_test_management_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        result = await agent._link_issue_to_test_case("TC-123", 10001, "Relates")

        assert "Successfully linked" in result
        mock_client.link_issue_to_test_case.assert_called_with("TC-123", 10001, "Relates")


@pytest.mark.asyncio
async def test_check_all_duplicates_batches_candidates_and_deduplicates_by_key(agent):
    test_case = TestCase(
        key="TC-123",
        labels=[],
        name="Sample Test Case",
        summary="Test case for testing",
        comment="",
        preconditions=None,
        steps=[],
        parent_issue_key=None,
    )
    input_data = IncidentCreationInput(
        test_case=test_case,
        test_execution_result="Failed with NPE",
        test_step_results=[],
        system_description="Win10",
        issue_priority_field_id="priority",
        issue_severity_field_name="Severity",
    )
    candidates = [
        DuplicateCandidate(issue_id="10001", key="BUG-1", content="First candidate content"),
        DuplicateCandidate(issue_id="10001", key="BUG-1", content="Duplicate candidate content"),
        DuplicateCandidate(issue_id="10002", key="BUG-2", content="Second candidate content"),
    ]
    expected_result = DuplicateDetectionResult(
        duplicates=[
            DuplicateIssue(issue_id="10001", issue_key="BUG-1", message="Same issue"),
        ],
        message="Found 1 duplicate out of 2 unique candidates.",
    )
    agent.duplicate_detector.run = AsyncMock(return_value=MagicMock(output=expected_result))

    result = await agent._check_all_duplicates(input_data, candidates)

    assert result == expected_result
    assert result.duplicates == expected_result.duplicates
    agent.duplicate_detector.run.assert_awaited_once()
    prompt = agent.duplicate_detector.run.await_args.args[0]
    assert '"key": "BUG-1"' in prompt
    assert '"key": "BUG-2"' in prompt
    assert "First candidate content" in prompt
    assert "Second candidate content" in prompt
    assert "Duplicate candidate content" not in prompt

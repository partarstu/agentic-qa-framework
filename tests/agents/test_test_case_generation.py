
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import sys

# Mock MCPServerSSE before importing the module
with patch("pydantic_ai.mcp.MCPServerSSE"):
    from agents.test_case_generation.main import TestCaseGenerationAgent

from common.models import GeneratedTestCases, AcceptanceCriteriaList, TestStepsSequenceList
from common.services.test_management_base import TestManagementClientBase

@pytest.fixture
def mock_config():
    with patch("agents.test_case_generation.main.config") as mock_conf:
        mock_conf.TestCaseGenerationAgentConfig.OWN_NAME = "generation_agent"
        mock_conf.AGENT_BASE_URL = "http://localhost"
        mock_conf.TestCaseGenerationAgentConfig.PORT = 8002
        mock_conf.TestCaseGenerationAgentConfig.EXTERNAL_PORT = 8002
        mock_conf.TestCaseGenerationAgentConfig.PROTOCOL = "http"
        mock_conf.TestCaseGenerationAgentConfig.MODEL_NAME = "test"
        mock_conf.TestCaseGenerationAgentConfig.THINKING_BUDGET = 2000
        mock_conf.TestCaseGenerationAgentConfig.MAX_REQUESTS_PER_TASK = 10
        mock_conf.JIRA_MCP_SERVER_URL = "http://jira-mcp"
        mock_conf.MCP_SERVER_TIMEOUT_SECONDS = 30
        yield mock_conf

@pytest.fixture
def agent(mock_config):
    # Patch PromptBase.get_prompt to avoid file reading issues
    with patch("agents.test_case_generation.prompt.TestCaseGenerationSystemPrompt.get_prompt", return_value="Prompt"), \
         patch("agents.test_case_generation.prompt.AcExtractionPrompt.get_prompt", return_value="AC Prompt"), \
         patch("agents.test_case_generation.prompt.StepsGenerationPrompt.get_prompt", return_value="Steps Prompt"), \
         patch("agents.test_case_generation.prompt.TestCaseCreationPrompt.get_prompt", return_value="TC Prompt"):
        
        # We also need to mock pydantic_ai.Agent used for sub-agents
        with patch("agents.test_case_generation.main.Agent") as mock_agent_cls:
            # Ensure Agent() returns a new mock each time
            mock_agent_cls.side_effect = lambda *args, **kwargs: MagicMock()
            
            agent_inst = TestCaseGenerationAgent()
            # Assign mocks to sub-agents if needed (Agent() returns a mock)
            # The init calls Agent(...) 3 times.
            # We can inspect agent_inst.ac_extractor_agent etc.
            yield agent_inst

def test_agent_init(agent, mock_config):
    assert agent.agent_name == "generation_agent"
    assert agent.get_thinking_budget() == 2000
    assert agent.get_max_requests_per_task() == 10
    
    assert agent.ac_extractor_agent is not None
    assert agent.steps_generator_agent is not None
    assert agent.test_case_creator_agent is not None

@pytest.mark.asyncio
async def test_generate_test_cases_flow(agent):
    # Setup return values for sub-agents
    mock_ac_result = MagicMock()
    mock_ac_result.output = AcceptanceCriteriaList(items=[])
    agent.ac_extractor_agent.run = AsyncMock(return_value=mock_ac_result)
    
    mock_steps_result = MagicMock()
    mock_steps_result.output = TestStepsSequenceList(items=[])
    agent.steps_generator_agent.run = AsyncMock(return_value=mock_steps_result)
    
    mock_tc_result = MagicMock()
    mock_tc_result.output = GeneratedTestCases(test_cases=[])
    agent.test_case_creator_agent.run = AsyncMock(return_value=mock_tc_result)
    
    # Mock _fetch_attachments to return empty dict
    agent._fetch_attachments = MagicMock(return_value={})
    
    # Pass file paths instead of BinaryContent objects
    result = await agent._generate_test_cases("Jira Content", ["/path/to/attachment.png"])
    
    assert isinstance(result, GeneratedTestCases)
    agent._fetch_attachments.assert_called_once_with(["/path/to/attachment.png"])
    agent.ac_extractor_agent.run.assert_called_once()
    agent.steps_generator_agent.run.assert_called_once()
    agent.test_case_creator_agent.run.assert_called_once()


@patch("agents.test_case_generation.main.get_test_management_client")
def test_upload_test_cases(mock_get_client, agent):
    mock_client = MagicMock(spec=TestManagementClientBase)
    mock_get_client.return_value = mock_client
    mock_client.create_test_cases.return_value = ["TC-1", "TC-2"]
    
    tcs = GeneratedTestCases(test_cases=[])
    result = agent._upload_test_cases_into_test_management_system(tcs, "PROJ", 123)
    
    mock_client.create_test_cases.assert_called_once()
    assert "TC-1, TC-2" in result

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from common.agent_base import AgentBase
from pydantic import BaseModel
from a2a.types import Message
from a2a.utils import get_message_text
import config

class TestAgent(AgentBase):
    __test__ = False
    def get_thinking_budget(self) -> int:
        return 1000

    def get_max_requests_per_task(self) -> int:
        return 5

from common.models import JsonSerializableModel

class MockOutput(JsonSerializableModel):
    result: str

@pytest.fixture
def test_agent_instance():
    with patch("common.agent_base.Agent") as mock_agent_cls: # Mock the actual pydantic_ai Agent class
        agent = TestAgent(
            agent_name="test-agent",
            base_url="http://localhost",
            protocol="http",
            port=8000,
            external_port=8000,
            model_name="openai:test-model",
            output_type=MockOutput,
            instructions="test instructions",
            mcp_servers=[]
        )
        return agent

def test_agent_initialization(test_agent_instance):
    assert test_agent_instance.agent_name == "test-agent"
    assert test_agent_instance.url == "http://localhost:8000"
    assert test_agent_instance.get_thinking_budget() == 1000

@pytest.mark.asyncio
async def test_agent_run_success(test_agent_instance):
    mock_run_result = MagicMock()
    mock_run_result.output = MockOutput(result="success")
    
    # Mock the internal agent's run method
    test_agent_instance.agent = AsyncMock()
    test_agent_instance.agent.run.return_value = mock_run_result
    test_agent_instance.agent.__aenter__.return_value = test_agent_instance.agent
    test_agent_instance.agent.__aexit__.return_value = None

    mock_message = MagicMock(spec=Message)
    # Mocking get_message_text utility call which happens inside _get_all_received_contents
    with patch("common.agent_base.get_message_text", return_value="hello"):
        mock_message.parts = []
        
        response = await test_agent_instance.run(mock_message)
        
        # Use raw string for regex-like escaping or double escape
        assert get_message_text(response) == '{"result":"success"}'

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.types import Message
from a2a.helpers import get_message_text
from pydantic_ai.usage import UsageLimits

from common.agent_base import AgentBase
from common.models import JsonSerializableModel
from common.streaming import report_activity


class TestAgent(AgentBase):
    __test__ = False

    def get_thinking_level(self) -> str:
        return "LOW"

    def get_max_requests_per_task(self) -> int:
        return 5


class MockOutput(JsonSerializableModel):
    result: str


@pytest.fixture
def test_agent_instance():
    with patch("common.agent_base.Agent"):  # Mock the actual pydantic_ai Agent class
        agent = TestAgent(
            agent_name="test-agent",
            base_url="http://localhost",
            protocol="http",
            port=8000,
            external_port=8000,
            model_name="openai:test-model",
            output_type=MockOutput,
            instructions="test instructions",
            mcp_servers=[],
        )
        return agent


def test_agent_initialization(test_agent_instance):
    assert test_agent_instance.agent_name == "test-agent"
    assert test_agent_instance.url == "http://localhost:8000"
    assert test_agent_instance.get_thinking_level() == "LOW"


def test_report_activity_auto_registered(test_agent_instance):
    """AgentBase with empty tools=() must expose report_activity in its tools list."""
    assert report_activity in test_agent_instance.tools


def test_no_extra_tools_added_beyond_report_activity():
    """When tools=() the resulting list contains exactly report_activity."""
    with patch("common.agent_base.Agent"):
        agent = TestAgent(
            agent_name="test-agent",
            base_url="http://localhost",
            protocol="http",
            port=8000,
            external_port=8000,
            model_name="openai:test-model",
            output_type=MockOutput,
            instructions="instructions",
            mcp_servers=[],
            tools=(),
        )
    assert agent.tools == [report_activity]


def test_instruction_snippet_appended(test_agent_instance):
    """The report_activity instruction snippet must be present at the end of instructions."""
    assert test_agent_instance.instructions.endswith(
        "\nA `report_activity` tool is available — use it as described in its tool description."
    )


@pytest.mark.asyncio
async def test_usage_limits_tool_calls_limit_is_doubled(test_agent_instance):
    """tool_calls_limit must equal get_max_requests_per_task() * 2."""
    captured: list[UsageLimits] = []

    async def fake_run(request, usage_limits=None):
        captured.append(usage_limits)
        mock_result = MagicMock()
        mock_result.output = MockOutput(result="ok")
        return mock_result

    test_agent_instance.agent = AsyncMock()
    test_agent_instance.agent.run = fake_run
    test_agent_instance.agent.__aenter__.return_value = test_agent_instance.agent
    test_agent_instance.agent.__aexit__.return_value = None

    with patch("common.agent_base.get_message_text", return_value="hello"):
        mock_message = MagicMock(spec=Message)
        mock_message.parts = []
        await test_agent_instance.run(mock_message)

    assert len(captured) == 1
    assert captured[0].tool_calls_limit == test_agent_instance.get_max_requests_per_task() * 2


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

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.helpers import get_message_text
from a2a.types import Message
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
from fastapi.testclient import TestClient
from pydantic_ai.usage import RunUsage

if TYPE_CHECKING:
    from pydantic_ai.usage import UsageLimits

import config
from common.agent_base import AgentBase
from common.agent_log_capture import AgentLogCaptureHandler
from common.models import JsonSerializableModel
from common.streaming import reset_current_log_handler, set_current_log_handler


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
            version="2.5",
            output_type=MockOutput,
            instructions="test instructions",
        )
        return agent


def test_agent_initialization(test_agent_instance):
    assert test_agent_instance.agent_name == "test-agent"
    assert test_agent_instance.url == "http://localhost:8000"
    assert test_agent_instance.get_thinking_level() == "LOW"


def test_report_activity_auto_registered(test_agent_instance):
    """AgentBase with empty tools=() must expose report_activity in its tools list."""
    assert test_agent_instance.report_activity in test_agent_instance.tools


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
            version="2.5",
            output_type=MockOutput,
            instructions="instructions",
            tools=(),
        )
    assert agent.tools == [agent.report_activity]


def test_instruction_snippet_appended(test_agent_instance):
    """The report_activity instruction snippet must be present at the end of instructions."""
    assert test_agent_instance.instructions.endswith(
        "\nA `report_activity` tool is available — call it before any other tool call or reasoning phase."
    )


@pytest.mark.asyncio
async def test_usage_limits_tool_calls_limit_is_doubled(test_agent_instance):
    """tool_calls_limit must equal get_max_requests_per_task() * 2."""
    captured: list[UsageLimits] = []

    async def fake_run(request, usage_limits=None, toolsets=None):
        captured.append(usage_limits)
        mock_result = MagicMock()
        mock_result.output = MockOutput(result="ok")
        mock_result.usage.return_value = RunUsage(input_tokens=10, output_tokens=5)
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
    assert captured[0].total_tokens_limit == config.BudgetConfig.TOTAL_TOKENS_LIMIT_PER_TASK


@pytest.mark.asyncio
async def test_agent_run_success(test_agent_instance):
    mock_run_result = MagicMock()
    mock_run_result.output = MockOutput(result="success")
    mock_run_result.usage.return_value = RunUsage(input_tokens=20, output_tokens=8)

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

    # The run's token usage is captured for the executor to emit as an artifact.
    assert test_agent_instance.latest_token_usage is not None
    assert test_agent_instance.latest_token_usage.input_tokens == 20
    assert test_agent_instance.latest_token_usage.total_tokens == 28


@pytest.mark.asyncio
async def test_activity_queue_bounded_and_drops_items(test_agent_instance):
    """When the queue hits its max limit, report_activity drops new items without raising."""
    for i in range(1005):
        await test_agent_instance.report_activity(f"activity-{i}")
    assert test_agent_instance.activity_queue.qsize() == 1000


def test_agent_card_carries_the_configured_version(test_agent_instance):
    """The version reported by the A2A agent card must be the one the agent was configured with."""
    client = TestClient(test_agent_instance.a2a_server)

    card = client.get(AGENT_CARD_WELL_KNOWN_PATH).json()

    assert card["version"] == "2.5"


@pytest.mark.asyncio
async def test_each_run_gets_a_fresh_mcp_toolset_whose_session_the_run_owns():
    """Sessions must be per request, and opened by the run itself so it can also re-open them."""
    built_toolsets: list[MagicMock] = []

    def build_toolset() -> MagicMock:
        toolset = MagicMock()
        toolset.__aenter__ = AsyncMock(return_value=toolset)
        toolset.__aexit__ = AsyncMock(return_value=None)
        built_toolsets.append(toolset)
        return toolset

    with patch("common.agent_base.Agent"):
        agent = TestAgent(
            agent_name="test-agent",
            base_url="http://localhost",
            protocol="http",
            port=8000,
            external_port=8000,
            model_name="openai:test-model",
            version="2.5",
            output_type=MockOutput,
            instructions="test instructions",
            mcp_toolset_factories=[build_toolset],
        )

    passed_toolsets: list[list[MagicMock]] = []

    async def fake_run(request, usage_limits=None, toolsets=None):
        passed_toolsets.append(toolsets)
        mock_result = MagicMock()
        mock_result.output = MockOutput(result="ok")
        mock_result.usage.return_value = RunUsage(input_tokens=10, output_tokens=5)
        return mock_result

    agent.agent = AsyncMock()
    agent.agent.run = fake_run
    agent.agent.__aenter__.return_value = agent.agent
    agent.agent.__aexit__.return_value = None

    with patch("common.agent_base.get_message_text", return_value="hello"):
        mock_message = MagicMock(spec=Message)
        mock_message.parts = []
        await agent.run(mock_message)
        await agent.run(mock_message)

    assert len(built_toolsets) == 2, "Each run must build its own toolset"
    assert built_toolsets[0] is not built_toolsets[1]
    assert passed_toolsets == [[built_toolsets[0]], [built_toolsets[1]]]
    for toolset in built_toolsets:
        # Entering it here as well would make the session count 2 and stop it from ever being torn
        # down mid-run, which is exactly what the self-healing reconnect needs to be able to do.
        toolset.__aenter__.assert_not_awaited()

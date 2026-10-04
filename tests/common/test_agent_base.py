# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import itertools
import logging
from collections.abc import Callable, Sequence
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2
import pytest
from a2a.helpers import get_message_text, new_data_part, new_text_part
from a2a.types import Message
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
from pydantic_ai import RunContext
from pydantic_ai.capabilities.abstract import leaf_capabilities
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.usage import RunUsage, UsageLimits
from pydantic_ai_harness.compaction import TieredCompaction

import config
from common.agent_base import _COMPACTION_KEEP_MESSAGES, AgentBase
from common.agent_log_capture import AgentLogCaptureHandler
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import AgentRuntimeError, AgentSkillDeclaration, JsonSerializableModel
from common.streaming import reset_current_log_handler, set_current_log_handler
from common.token_usage import OperationMeter, operation_meter


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
            skill=AgentSkillDeclaration(
                id="test-skill",
                name="Test Skill",
                description="Skill used by the unit-test agent",
            ),
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
            skill=AgentSkillDeclaration(
                id="test-skill",
                name="Test Skill",
                description="Skill used by the unit-test agent",
            ),
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

    async def fake_run(request, usage_limits=None, toolsets=None, **kwargs):
        captured.append(usage_limits)
        mock_result = MagicMock()
        mock_result.output = MockOutput(result="ok")
        mock_result.usage = RunUsage(input_tokens=10, output_tokens=5)
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
    assert captured[0].request_limit == UsageLimits().request_limit


@pytest.mark.asyncio
async def test_agent_run_success(test_agent_instance):
    mock_run_result = MagicMock()
    mock_run_result.output = MockOutput(result="success")
    mock_run_result.usage = RunUsage(input_tokens=20, output_tokens=8)

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


def test_token_usage_includes_nested_calls_recorded_in_the_operation_meter(test_agent_instance):
    meter = OperationMeter()
    meter.add("main", "openai:test-model", RunUsage(requests=1, input_tokens=20, output_tokens=8))
    meter.add("sub_agent", "openai:test-model", RunUsage(requests=3, input_tokens=40, output_tokens=12))
    main_run_result = MagicMock()
    main_run_result.usage = RunUsage(requests=1, input_tokens=20, output_tokens=8)

    token = operation_meter.set(meter)
    try:
        test_agent_instance._capture_token_usage(main_run_result)
    finally:
        operation_meter.reset(token)

    token_usage = test_agent_instance.latest_token_usage
    assert token_usage.requests == 4
    assert token_usage.input_tokens == 60
    assert token_usage.total_tokens == 80
    assert token_usage.operations == meter.entries()


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
            skill=AgentSkillDeclaration(
                id="test-skill",
                name="Test Skill",
                description="Skill used by the unit-test agent",
            ),
            output_type=MockOutput,
            instructions="test instructions",
            mcp_toolset_factories=[build_toolset],
        )

    passed_toolsets: list[list[MagicMock]] = []

    async def fake_run(request, usage_limits=None, toolsets=None, **kwargs):
        passed_toolsets.append(toolsets)
        mock_result = MagicMock()
        mock_result.output = MockOutput(result="ok")
        mock_result.usage = RunUsage(input_tokens=10, output_tokens=5)
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


def _agent_whose_run_raises(agent: TestAgent, *effects) -> AsyncMock:
    agent.agent = AsyncMock()
    agent.agent.run = AsyncMock(side_effect=list(effects))
    agent.agent.__aenter__.return_value = agent.agent
    agent.agent.__aexit__.return_value = None
    return agent.agent.run


def _mcp_connect_failure() -> RuntimeError:
    try:
        raise RuntimeError("Client failed to connect") from httpx2.ConnectError("All connection attempts failed")
    except RuntimeError as e:
        return e


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [_mcp_connect_failure(), ExceptionGroup("g", [_mcp_connect_failure()])],
    ids=["bare", "exception-group"],
)
async def test_mcp_connect_failure_is_reported_as_a_connection_error(test_agent_instance, failure):
    test_agent_instance.mcp_toolset_factories = [MagicMock]
    _agent_whose_run_raises(test_agent_instance, failure)

    with pytest.raises(ConnectionError, match="MCP connection failed"):
        await test_agent_instance._get_agent_execution_result([], None, UsageLimits())


@pytest.mark.asyncio
async def test_run_failure_without_a_connect_error_propagates_unchanged(test_agent_instance):
    test_agent_instance.mcp_toolset_factories = [MagicMock]
    _agent_whose_run_raises(test_agent_instance, RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await test_agent_instance._get_agent_execution_result([], None, UsageLimits())


@pytest.mark.asyncio
async def test_model_transport_error_is_retried(test_agent_instance):
    result = MagicMock()
    run = _agent_whose_run_raises(test_agent_instance, httpx2.ReadError("reset"), result)

    with patch("common.agent_base.asyncio.sleep", new=AsyncMock()):
        assert await test_agent_instance._get_agent_execution_result([], None, UsageLimits()) is result
    assert run.await_count == 2


@pytest.mark.asyncio
async def test_retryable_provider_errors_of_concurrent_sub_agent_runs_are_retried(test_agent_instance):
    result = MagicMock()
    failure = ExceptionGroup("reviews", [httpx2.ReadError("reset"), ModelHTTPError(500, "gemini")])
    run = _agent_whose_run_raises(test_agent_instance, failure, result)

    with patch("common.agent_base.asyncio.sleep", new=AsyncMock()):
        assert await test_agent_instance._get_agent_execution_result([], None, UsageLimits()) is result
    assert run.await_count == 2


@pytest.mark.asyncio
async def test_a_group_with_a_non_retryable_error_propagates_without_a_retry(test_agent_instance):
    failure = ExceptionGroup("reviews", [httpx2.ReadError("reset"), ModelHTTPError(400, "gemini")])
    run = _agent_whose_run_raises(test_agent_instance, failure, MagicMock())

    with pytest.raises(ExceptionGroup) as raised:
        await test_agent_instance._get_agent_execution_result([], None, UsageLimits())
    assert raised.value is failure
    assert run.await_count == 1


@pytest.mark.asyncio
async def test_model_connect_error_in_an_mcp_agent_is_retried_not_blamed_on_mcp(test_agent_instance):
    test_agent_instance.mcp_toolset_factories = [MagicMock]
    result = MagicMock()
    run = _agent_whose_run_raises(test_agent_instance, httpx2.ConnectError("model endpoint unreachable"), result)

    with patch("common.agent_base.asyncio.sleep", new=AsyncMock()):
        assert await test_agent_instance._get_agent_execution_result([], None, UsageLimits()) is result
    assert run.await_count == 2


def test_skill_is_required_at_construction():
    """An agent without a declared skill must fail instead of falling back to a generic one."""
    with patch("common.agent_base.Agent"), pytest.raises(TypeError):
        TestAgent(
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


def test_card_description_composes_model_version_and_skill():
    """The card description carries model, version and skill name, line-separated."""
    with patch("common.agent_base.Agent"):
        agent = TestAgent(
            agent_name="test-agent",
            base_url="http://localhost",
            protocol="http",
            port=8000,
            external_port=8000,
            model_name="openai:test-model",
            version="2.5",
            skill=AgentSkillDeclaration(
                id="test-skill",
                name="Test Skill",
                description="Skill used by the unit-test agent",
            ),
            output_type=MockOutput,
            instructions="test instructions",
        )
    description = agent._compose_card_description()
    assert "openai:test-model" in description
    assert "2.5" in description
    assert "Test Skill" in description
    assert "<br>" in description


@pytest.mark.asyncio
async def test_agent_run_reaches_its_tools_with_their_arguments() -> None:
    """A tool must receive everything it needs from its own parameters.

    ``AgentBase.run`` starts the agent without dependencies, so a tool that expects them
    (``ctx.deps``) fails at the first call. Running a tool through the real agent, instead of
    calling it directly, is what catches that.
    """
    tool_calls: list[tuple[str, str]] = []

    async def review_issue(jira_issue_key: str, jira_issue_content: str) -> str:
        """Reviews the Jira issue with the given key."""
        tool_calls.append((jira_issue_key, jira_issue_content))
        return "reviewed"

    agent = TestAgent(
        agent_name="test-agent",
        base_url="http://localhost",
        protocol="http",
        port=8000,
        external_port=8000,
        model_name="openai:test-model",
        version="2.5",
        skill=AgentSkillDeclaration(
            id="test-skill",
            name="Test Skill",
            description="Skill used by the unit-test agent",
        ),
        output_type=MockOutput,
        instructions="test instructions",
        tools=[review_issue],
    )

    message = MagicMock(spec=Message)
    message.parts = []
    with (
        agent.agent.override(model=TestModel()),
        patch("common.agent_base.get_message_text", return_value="Jira user story with key PROJ-1"),
    ):
        await agent.run(message)

    assert tool_calls, "The agent run never reached the tool."
    assert all(key and content for key, content in tool_calls), f"A tool argument was empty: {tool_calls}"


class _Deps(BaseModel):
    model_config = ConfigDict(extra="forbid")
    story_key: str
    seen_by: list[str] = []


def _agent_with(name: str, tools=(), deps_type: type[BaseModel] | None = _Deps, agent_class=TestAgent) -> TestAgent:
    return agent_class(
        agent_name=name,
        base_url="http://localhost",
        protocol="http",
        port=8000,
        external_port=8000,
        model_name="openai:test-model",
        version="2.5",
        skill=AgentSkillDeclaration(id=f"{name}-skill", name=name, description="Skill used by unit tests"),
        output_type=MockOutput,
        instructions="test instructions",
        tools=tools,
        deps_type=deps_type,
    )


def _message(*parts) -> Message:
    return Message(message_id="m-1", parts=list(parts))


@pytest.mark.asyncio
async def test_structured_data_part_becomes_the_deps_of_the_run() -> None:
    received: list[_Deps] = []

    async def record_deps(ctx: RunContext[_Deps]) -> str:
        """Records the deps of the run."""
        received.append(ctx.deps)
        return "recorded"

    agent = _agent_with("parent", tools=[record_deps])

    with agent.agent.override(model=TestModel()):
        await agent.run(_message(new_text_part("Design PROJ-1"), new_data_part({"story_key": "PROJ-1"})))

    assert received and all(deps == _Deps(story_key="PROJ-1") for deps in received)


@pytest.mark.asyncio
async def test_data_part_with_unknown_fields_fails_the_run() -> None:
    agent = _agent_with("parent")

    with agent.agent.override(model=TestModel()), pytest.raises(AgentRuntimeError, match="extra"):
        await agent.run(_message(new_text_part("Design PROJ-1"), new_data_part({"story_key": "P-1", "x": 1})))


@pytest.mark.asyncio
async def test_more_than_one_data_part_fails_the_run() -> None:
    agent = _agent_with("parent")
    part = new_data_part({"story_key": "PROJ-1"})

    with agent.agent.override(model=TestModel()), pytest.raises(AgentRuntimeError, match="at most one"):
        await agent.run(_message(new_text_part("Design PROJ-1"), part, part))


def test_data_part_is_ignored_by_an_agent_without_deps_type(test_agent_instance) -> None:
    assert test_agent_instance._get_deps(_message(new_data_part({"story_key": "PROJ-1"}))) is None


@pytest.mark.asyncio
async def test_delegated_run_shares_deps_usage_limits_and_activity_queue_of_the_delegating_task() -> None:
    child_limits: list[UsageLimits] = []

    async def child_tool(ctx: RunContext[_Deps]) -> str:
        """Marks the deps as seen by the child."""
        ctx.deps.seen_by.append("child")
        return "done"

    child = _agent_with("child", tools=[child_tool])
    child_run = child.agent.run

    async def spy_run(*args, **kwargs):
        child_limits.append(kwargs["usage_limits"])
        return await child_run(*args, **kwargs)

    child.agent.run = spy_run
    delegated_outputs: list[str] = []

    async def delegate(ctx: RunContext[_Deps]) -> str:
        """Delegates to the child agent."""
        delegated_outputs.append(await child.run_delegated("Do it", ctx.deps, ctx.usage))
        return "delegated"

    parent = _agent_with("parent", tools=[delegate])
    captured_deps: list[_Deps] = []
    parent_run = parent.agent.run

    async def parent_spy_run(*args, **kwargs):
        captured_deps.append(kwargs["deps"])
        return await parent_run(*args, **kwargs)

    parent.agent.run = parent_spy_run

    with parent.agent.override(model=TestModel()), child.agent.override(model=TestModel()):
        await parent.run(_message(new_text_part("Design PROJ-1"), new_data_part({"story_key": "PROJ-1"})))

    assert delegated_outputs and all(isinstance(output, str) for output in delegated_outputs)
    assert "child" in captured_deps[0].seen_by
    assert child_limits[0] == parent._get_usage_limits()
    assert child.activity_queue.empty(), "A delegated run must report to the delegating task's queue"
    assert not parent.activity_queue.empty()


@pytest.mark.asyncio
async def test_delegated_run_outside_a_task_uses_its_own_limits_and_queue() -> None:
    agent = _agent_with("child")
    agent.agent = AsyncMock()
    agent.agent.run = AsyncMock(return_value=MagicMock(output="closing text"))
    agent.agent.__aenter__.return_value = agent.agent
    agent.agent.__aexit__.return_value = None
    deps = _Deps(story_key="PROJ-1")
    usage = RunUsage()

    assert await agent.run_delegated("Do it", deps, usage) == "closing text"

    kwargs = agent.agent.run.await_args.kwargs
    assert kwargs["deps"] is deps
    assert kwargs["usage"] is usage
    assert kwargs["output_type"] is str
    assert kwargs["usage_limits"] == agent._get_usage_limits()
    await agent.report_activity("working")
    assert agent.activity_queue.qsize() == 1


class _BigBudgetAgent(TestAgent):
    __test__ = False

    def get_total_tokens_limit(self) -> int:
        return 4_000_000


class _UncappedAgent(TestAgent):
    __test__ = False

    def get_request_limit(self) -> int | None:
        return None


def test_an_agent_can_lift_the_request_cap_of_its_tasks() -> None:
    assert _agent_with("uncapped", agent_class=_UncappedAgent)._get_usage_limits().request_limit is None


def test_sub_agent_limits_cap_only_the_tokens_of_the_task() -> None:
    agent = _agent_with("big", agent_class=_BigBudgetAgent)

    limits = agent.get_sub_agent_usage_limits()

    assert (limits.total_tokens_limit, limits.tool_calls_limit, limits.request_limit) == (4_000_000, None, None)


def test_total_tokens_limit_defaults_to_the_global_budget_and_can_be_overridden() -> None:
    assert _agent_with("default").get_total_tokens_limit() == config.BudgetConfig.TOTAL_TOKENS_LIMIT_PER_TASK
    assert _agent_with("big", agent_class=_BigBudgetAgent)._get_usage_limits().total_tokens_limit == 4_000_000


_COMPACTION_TEST_WINDOW = 10_000
_CLEARED_PLACEHOLDER = "[tool result cleared]"


def _fetch_result(index: int) -> str:
    return f"result {index} " + "lorem ipsum " * 300


def fetch(index: int) -> str:
    """Fetches the document with the given index."""
    return _fetch_result(index)


def noop() -> str:
    """Does nothing."""
    return "ok"


type _Respond = Callable[[int, AgentInfo], ModelResponse]


async def _run_compacting_agent(
    tools: Sequence[Callable[..., str]], respond: _Respond
) -> tuple[list[list[ModelMessage]], MockOutput]:
    """Run an AgentBase agent on a small-window model, returning the history each request carried and the output."""
    received: list[list[ModelMessage]] = []

    def record_and_respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        received.append(list(messages))
        return respond(len(received), info)

    agent = _agent_with("compacting", tools=tools, deps_type=None)
    model = FunctionModel(record_and_respond, profile=ModelProfile(context_window=_COMPACTION_TEST_WINDOW))
    with agent.agent.override(model=model):
        result = await agent.agent.run("the task")
    return received, result.output


def _final_output(info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"result": "done"})])


def _fetch_calls(count: int) -> _Respond:
    def respond(request_number: int, info: AgentInfo) -> ModelResponse:
        if request_number > count:
            return _final_output(info)
        return ModelResponse(parts=[ToolCallPart("fetch", {"index": request_number})])

    return respond


def _tool_returns(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    return [
        part
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]


def _assert_task_prompt_and_tool_pairs_intact(messages: list[ModelMessage]) -> None:
    first_parts = messages[0].parts
    assert any(isinstance(part, UserPromptPart) and part.content == "the task" for part in first_parts)
    call_ids = {
        part.tool_call_id
        for message in messages
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, ToolCallPart)
    }
    assert call_ids == {part.tool_call_id for part in _tool_returns(messages)}


@pytest.mark.asyncio
async def test_history_below_the_compaction_target_reaches_the_model_unchanged() -> None:
    received, output = await _run_compacting_agent([fetch], _fetch_calls(3))

    assert output == MockOutput(result="done")
    assert [part.content for part in _tool_returns(received[-1])] == [_fetch_result(index) for index in (1, 2, 3)]


@pytest.mark.asyncio
async def test_history_over_the_compaction_target_clears_old_tool_results_and_keeps_the_newest_pairs() -> None:
    received, output = await _run_compacting_agent([fetch], _fetch_calls(20))

    assert output == MockOutput(result="done")
    final_history = received[-1]
    returns = _tool_returns(final_history)
    # All 20 pairs are still present: clearing the results was enough, so no turn was dropped.
    assert len(returns) == 20
    assert returns[0].content == _CLEARED_PLACEHOLDER
    assert [part.content for part in returns[-6:]] == [_fetch_result(index) for index in range(15, 21)]
    _assert_task_prompt_and_tool_pairs_intact(final_history)


@pytest.mark.asyncio
async def test_history_still_over_target_after_clearing_drops_the_oldest_turns() -> None:
    turns = 30

    def respond(request_number: int, info: AgentInfo) -> ModelResponse:
        if request_number > turns:
            return _final_output(info)
        return ModelResponse(parts=[TextPart("thinking aloud " * 150), ToolCallPart("noop", {})])

    received, output = await _run_compacting_agent([noop], respond)

    assert output == MockOutput(result="done")
    compacted_histories = [later for earlier, later in itertools.pairwise(received) if len(later) < len(earlier)]
    assert compacted_histories
    # The window keeps the newest messages and re-adds the task prompt in front of them.
    assert all(len(history) <= _COMPACTION_KEEP_MESSAGES + 1 for history in compacted_histories)
    _assert_task_prompt_and_tool_pairs_intact(received[-1])


def test_agent_base_agent_carries_context_compaction_but_a_sub_agent_does_not() -> None:
    sub_agent = CustomLlmWrapper.create_agent("openai:test-model", output_type=MockOutput)

    assert any(
        isinstance(cap, TieredCompaction) for cap in leaf_capabilities(_agent_with("main").agent.root_capability)
    )
    assert not any(isinstance(cap, TieredCompaction) for cap in leaf_capabilities(sub_agent.root_capability))

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, Artifact, Part, TaskArtifactUpdateEvent

import config
from common.streaming import AgentActivityEvent, LogBatchEvent, TaskDoneEvent
from orchestrator.main import (
    AgentStatus,
    BrokenReason,
    _discover_agents,
    _fetch_agent_card,
    _finalize_task,
    _handle_stream_chunk,
    _LogStreamState,
    _select_agent,
    agent_registry,
    discovery_agent,
)
from orchestrator.models import TaskStatus


@pytest.fixture
async def clear_registry():
    # Clear registry before/after test
    agent_registry._cards.clear()
    agent_registry._statuses.clear()
    agent_registry._broken_reasons.clear()
    agent_registry._stuck_task_ids.clear()
    yield
    agent_registry._cards.clear()
    agent_registry._statuses.clear()
    agent_registry._broken_reasons.clear()
    agent_registry._stuck_task_ids.clear()


@pytest.fixture
def mock_agent_card():
    return AgentCard(
        name="Discovered Agent",
        description="Desc",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=[],
        default_input_modes=["text"],
        default_output_modes=["text"],
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url="http://localhost:8001")],
    )


@pytest.mark.asyncio
async def test_fetch_agent_card_success(mock_agent_card):
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        from google.protobuf.json_format import MessageToDict

        mock_response.json.return_value = MessageToDict(mock_agent_card, preserving_proto_field_name=True)
        mock_client.get.return_value = mock_response

        card = await _fetch_agent_card("http://localhost:8001")
        assert card.name == "Discovered Agent"


@pytest.mark.asyncio
async def test_fetch_agent_card_failure():
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        mock_client.get.side_effect = Exception("Connection error")

        card = await _fetch_agent_card("http://bad-url")
        assert card is None


@pytest.mark.asyncio
async def test_discover_agents_success(clear_registry, mock_agent_card):
    with (
        patch("config.OrchestratorConfig.REMOTE_EXECUTION_AGENT_HOSTS", "http://localhost"),
        patch("config.OrchestratorConfig.AGENT_DISCOVERY_PORTS", "8001-8001"),
        patch("orchestrator.main._fetch_agent_card", return_value=mock_agent_card),
    ):
        await _discover_agents()

        assert not await agent_registry.is_empty()
        cards = await agent_registry.get_all_cards()
        assert len(cards) == 1
        assert next(iter(cards.values())).name == "Discovered Agent"


@pytest.mark.asyncio
async def test_select_agent(clear_registry, mock_agent_card):
    # Register an agent first
    await agent_registry.register("test-id", mock_agent_card)

    # Mock LLM response
    mock_result = MagicMock()
    mock_result.output.id = "test-id"

    # Mock discovery agent run
    with patch.object(discovery_agent, "run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_result

        agent_id = await _select_agent("some task", ["test-id"])
        assert agent_id == "test-id"


@pytest.mark.asyncio
async def test_select_agent_none_found(clear_registry):
    agent_id = await _select_agent("some task", [])
    assert agent_id is None


@pytest.mark.asyncio
async def test_discover_agents_existing_reachable(clear_registry, mock_agent_card):
    # Pre-register the agent
    await agent_registry.register("existing-id", mock_agent_card)

    with (
        patch("config.OrchestratorConfig.REMOTE_EXECUTION_AGENT_HOSTS", "http://localhost"),
        patch("config.OrchestratorConfig.AGENT_DISCOVERY_PORTS", "8001-8001"),
        patch("orchestrator.main._fetch_agent_card", return_value=mock_agent_card) as mock_fetch,
        patch("orchestrator.main._check_agent_reachability", return_value=True) as mock_check,
    ):
        await _discover_agents()

        # Verify _fetch_agent_card was NOT called
        mock_fetch.assert_not_called()
        # Verify check was called
        mock_check.assert_called_once_with("http://localhost:8001")

        # Verify agent is still there
        assert await agent_registry.contains("existing-id")


@pytest.mark.asyncio
async def test_discover_agents_existing_unreachable(clear_registry, mock_agent_card):
    # Pre-register the agent
    await agent_registry.register("existing-id", mock_agent_card)

    with (
        patch("config.OrchestratorConfig.REMOTE_EXECUTION_AGENT_HOSTS", "http://localhost"),
        patch("config.OrchestratorConfig.AGENT_DISCOVERY_PORTS", "8001-8001"),
        patch("orchestrator.main._fetch_agent_card", return_value=mock_agent_card),
        patch("orchestrator.main._check_agent_reachability", return_value=False) as mock_check,
    ):
        await _discover_agents()

        mock_check.assert_called_once_with("http://localhost:8001")

        # Verify agent REMOVED
        assert not await agent_registry.contains("existing-id")


@pytest.mark.asyncio
async def test_discover_agents_existing_recovery(clear_registry, mock_agent_card):
    # Pre-register the agent as BROKEN/OFFLINE
    await agent_registry.register("existing-id", mock_agent_card)
    await agent_registry.update_status("existing-id", AgentStatus.BROKEN, BrokenReason.OFFLINE)

    with (
        patch("config.OrchestratorConfig.REMOTE_EXECUTION_AGENT_HOSTS", "http://localhost"),
        patch("config.OrchestratorConfig.AGENT_DISCOVERY_PORTS", "8001-8001"),
        patch("orchestrator.main._fetch_agent_card", return_value=mock_agent_card),
        patch("orchestrator.main._check_agent_reachability", return_value=True),
    ):
        await _discover_agents()

        # Verify agent RECOVERED
        assert await agent_registry.get_status("existing-id") == AgentStatus.AVAILABLE


@pytest.mark.asyncio
async def test_discover_agents_fetches_new(clear_registry, mock_agent_card):
    # Registry empty

    with (
        patch("config.OrchestratorConfig.REMOTE_EXECUTION_AGENT_HOSTS", "http://localhost"),
        patch("config.OrchestratorConfig.AGENT_DISCOVERY_PORTS", "8001-8001"),
        patch("orchestrator.main._fetch_agent_card", return_value=mock_agent_card) as mock_fetch,
    ):
        await _discover_agents()

        # Verify _fetch_agent_card WAS called
        mock_fetch.assert_called_once_with("http://localhost:8001")


# =============================================================================
# _handle_stream_chunk
# =============================================================================


def _text_artifact(name: str, text: str) -> Artifact:
    return Artifact(name=name, parts=[Part(text=text)])


def _raw_artifact(name: str, raw_data: bytes, artifact_id: str = "logs-123") -> Artifact:
    return Artifact(name=name, artifact_id=artifact_id, parts=[Part(raw=raw_data, media_type="text/plain")])


@pytest.mark.asyncio
async def test_handle_stream_chunk_log_batch_updates_history_and_publishes_to_agent():
    artifact = _raw_artifact("logs", b"line1\nline2", "logs-123")
    collected: list[Artifact] = []
    log_state = _LogStreamState()
    event = TaskArtifactUpdateEvent(
        context_id="ctx-1",
        task_id="task-1",
        artifact=artifact,
        last_chunk=False,
    )

    with (
        patch("orchestrator.main.task_history") as mock_history,
        patch("orchestrator.main.streaming_hub") as mock_hub,
    ):
        mock_history.append_log_batch = AsyncMock()
        mock_hub.publish_agent = AsyncMock()

        await _handle_stream_chunk(event, "task-1", "agent-1", collected, log_state)

    mock_history.append_log_batch.assert_called_once_with("task-1", ["line1", "line2"])
    mock_hub.publish_agent.assert_called_once()
    published = mock_hub.publish_agent.call_args[0][1]
    assert published["type"] == "log_batch"
    assert "line1" in published["lines"]
    assert log_state.artifact_id == "logs-123"
    assert log_state.lines == ["line1", "line2"]
    assert collected == []


@pytest.mark.asyncio
async def test_handle_stream_chunk_log_last_chunk_consolidates():
    collected: list[Artifact] = []
    log_state = _LogStreamState()

    # Chunk 1
    artifact_1 = _raw_artifact("logs", b"line1\n", "logs-123")
    event_1 = TaskArtifactUpdateEvent(
        context_id="ctx-1",
        task_id="task-1",
        artifact=artifact_1,
        last_chunk=False,
    )
    with (
        patch("orchestrator.main.task_history") as mock_history,
        patch("orchestrator.main.streaming_hub") as mock_hub,
    ):
        mock_history.append_log_batch = AsyncMock()
        mock_hub.publish_agent = AsyncMock()
        await _handle_stream_chunk(event_1, "task-1", "agent-1", collected, log_state)

    # Chunk 2 (last)
    artifact_2 = _raw_artifact("logs", b"line2", "logs-123")
    event_2 = TaskArtifactUpdateEvent(
        context_id="ctx-1",
        task_id="task-1",
        artifact=artifact_2,
        last_chunk=True,
    )
    with (
        patch("orchestrator.main.task_history") as mock_history,
        patch("orchestrator.main.streaming_hub") as mock_hub,
    ):
        mock_history.append_log_batch = AsyncMock()
        mock_hub.publish_agent = AsyncMock()
        await _handle_stream_chunk(event_2, "task-1", "agent-1", collected, log_state)

    # Shoud have created a consolidated logs artifact
    assert len(collected) == 1
    consolidated = collected[0]
    assert consolidated.name == "logs"
    assert len(consolidated.parts) == 1
    assert consolidated.parts[0].filename == "execution_logs.txt"
    assert consolidated.parts[0].raw == b"line1\nline2"


@pytest.mark.asyncio
async def test_handle_stream_chunk_other_artifact_appended_to_collected():
    artifact = _text_artifact("agent_execution_result", '{"result": "ok"}')
    collected: list[Artifact] = []
    log_state = _LogStreamState()
    event = TaskArtifactUpdateEvent(
        context_id="ctx-1",
        task_id="task-1",
        artifact=artifact,
        last_chunk=False,
    )

    with (
        patch("orchestrator.main.task_history"),
        patch("orchestrator.main.streaming_hub"),
    ):
        await _handle_stream_chunk(event, "task-1", "agent-1", collected, log_state)

    assert len(collected) == 1
    assert collected[0] == artifact


# =============================================================================
# _finalize_task
# =============================================================================


@pytest.mark.asyncio
async def test_finalize_task_updates_history_and_publishes_task_done():
    with (
        patch("orchestrator.main.task_history") as mock_history,
        patch("orchestrator.main.streaming_hub") as mock_hub,
    ):
        mock_history.update = AsyncMock()
        mock_history.clear_current_activity = AsyncMock()
        mock_hub.publish_global = AsyncMock()
        mock_hub.publish_agent = AsyncMock()

        await _finalize_task("task-1", "agent-1", TaskStatus.COMPLETED)

    mock_history.update.assert_called_once()
    update_args = mock_history.update.call_args[0]
    assert update_args[0] == "task-1"
    assert update_args[1] == TaskStatus.COMPLETED

    mock_history.clear_current_activity.assert_called_once_with("task-1")

    mock_hub.publish_global.assert_called_once()
    global_event = mock_hub.publish_global.call_args[0][0]
    assert global_event["type"] == "task_done"
    assert global_event["task_id"] == "task-1"
    assert global_event["agent_id"] == "agent-1"
    assert global_event["status"] == TaskStatus.COMPLETED.value

    mock_hub.publish_agent.assert_called_once()
    agent_event = mock_hub.publish_agent.call_args[0][1]
    assert agent_event["type"] == "task_done"


@pytest.mark.asyncio
async def test_finalize_task_includes_error_message_when_provided():
    with (
        patch("orchestrator.main.task_history") as mock_history,
        patch("orchestrator.main.streaming_hub") as mock_hub,
    ):
        mock_history.update = AsyncMock()
        mock_history.clear_current_activity = AsyncMock()
        mock_hub.publish_global = AsyncMock()
        mock_hub.publish_agent = AsyncMock()

        await _finalize_task("task-1", "agent-1", TaskStatus.FAILED, "something broke")

    global_event = mock_hub.publish_global.call_args[0][0]
    assert global_event["error_message"] == "something broke"

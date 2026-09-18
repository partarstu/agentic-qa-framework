# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Artifact,
    Part,
    TaskArtifactUpdateEvent,
)
from fastapi import HTTPException

import config
from common.models import RoutingOutcome
from common.streaming import AgentActivityEvent, LogBatchEvent, TaskDoneEvent
from orchestrator.main import (
    AgentStatus,
    BrokenReason,
    _discover_agents,
    _fetch_agent_card,
    _finalize_task,
    _get_agents_info,
    _handle_stream_chunk,
    _health_check_agents,
    _LogStreamState,
    _route_task,
    _run_manual_discovery,
    _select_agent,
    agent_registry,
    cancellation_queue,
    discovery_agent,
    reserve_agent_waiting_if_needed,
)
from orchestrator.models import TaskStatus


def _drain_queue(queue):
    while not queue.empty():
        queue.get_nowait()


@pytest.fixture
async def clear_registry():
    # Clear registry before/after test
    agent_registry._cards.clear()
    agent_registry._statuses.clear()
    agent_registry._broken_reasons.clear()
    agent_registry._stuck_task_ids.clear()
    agent_registry._discovery_urls.clear()
    _drain_queue(cancellation_queue)
    yield
    agent_registry._cards.clear()
    agent_registry._statuses.clear()
    agent_registry._broken_reasons.clear()
    agent_registry._stuck_task_ids.clear()
    agent_registry._discovery_urls.clear()
    _drain_queue(cancellation_queue)


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


def _routing_result(outcome: RoutingOutcome, selected_agent_id: str | None = None) -> MagicMock:
    """Mocked discovery agent run result for one routing decision."""
    mock_result = MagicMock()
    mock_result.output.outcome = outcome
    mock_result.output.selected_agent_id = selected_agent_id
    mock_result.output.justification = "Test justification."
    return mock_result


def _routing_decision(outcome: RoutingOutcome, selected_agent_id: str | None = None) -> MagicMock:
    """Mocked routing decision as ``_route_task`` returns it (no ``output`` wrapper)."""
    decision = MagicMock()
    decision.outcome = outcome
    decision.selected_agent_id = selected_agent_id
    decision.justification = "Test justification."
    return decision


@pytest.mark.asyncio
async def test_route_task_agent_selected(clear_registry, mock_agent_card):
    # Register an agent first
    await agent_registry.register("test-id", mock_agent_card)

    with patch.object(discovery_agent, "run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = _routing_result(RoutingOutcome.AGENT_SELECTED, "test-id")

        agent_id = await _select_agent("some task", ["test-id"])
        assert agent_id == "test-id"


@pytest.mark.asyncio
async def test_route_task_suitable_but_busy(clear_registry, mock_agent_card):
    await agent_registry.register("test-id", mock_agent_card)

    with patch.object(discovery_agent, "run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = _routing_result(RoutingOutcome.SUITABLE_BUT_BUSY)

        agent_id = await _select_agent("some task", [])
        assert agent_id is None


@pytest.mark.asyncio
async def test_route_task_none_suitable(clear_registry, mock_agent_card):
    await agent_registry.register("test-id", mock_agent_card)

    with patch.object(discovery_agent, "run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = _routing_result(RoutingOutcome.NONE_SUITABLE)

        decision = await _route_task("some task")
        assert decision.outcome == RoutingOutcome.NONE_SUITABLE
        assert decision.selected_agent_id is None


@pytest.mark.asyncio
async def test_route_task_no_agents_registered(clear_registry):
    # No routing model call happens when no agents are registered at all
    with patch.object(discovery_agent, "run", new_callable=AsyncMock) as mock_run:
        decision = await _route_task("some task")
        assert decision.outcome == RoutingOutcome.NONE_SUITABLE
        mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_select_agent_none_found(clear_registry, mock_agent_card):
    # A suitable agent exists but is busy: nothing is selected among the available agents
    await agent_registry.register("test-id", mock_agent_card)

    with patch.object(discovery_agent, "run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = _routing_result(RoutingOutcome.SUITABLE_BUT_BUSY)

        agent_id = await _select_agent("some task", [])
        assert agent_id is None


# =============================================================================
# Agent reservation outcomes (WS1)
# =============================================================================


@pytest.fixture
def mock_error_history():
    """Mock error_history to prevent asyncio event loop issues."""
    with patch("orchestrator.main.error_history") as mock:
        mock.add = AsyncMock()
        yield mock


@pytest.fixture
def single_retry_then_timeout(monkeypatch):
    """One full wait-and-retry loop pass, then the wait budget is exhausted."""
    fake_time = MagicMock()
    fake_time.time.side_effect = [0, 0, config.OrchestratorConfig.TASK_EXECUTION_TIMEOUT + 1]
    monkeypatch.setattr("orchestrator.main.time", fake_time)
    monkeypatch.setattr("orchestrator.main.asyncio.sleep", AsyncMock())


@pytest.mark.asyncio
async def test_reserve_none_suitable_fails_fast_with_404_and_dashboard_error(
    clear_registry, mock_agent_card, mock_error_history
):
    await agent_registry.register("test-id", mock_agent_card)

    with (
        patch(
            "orchestrator.main._route_task",
            new_callable=AsyncMock,
            return_value=_routing_decision(RoutingOutcome.NONE_SUITABLE),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await reserve_agent_waiting_if_needed("some task", task_id="task-1")

    assert exc_info.value.status_code == 404
    assert "No registered agent can execute task" in exc_info.value.detail
    assert "Test justification." in exc_info.value.detail
    mock_error_history.add.assert_called()


@pytest.mark.asyncio
async def test_reserve_busy_timeout_names_suitable_but_busy_with_last_justification(
    clear_registry, mock_agent_card, mock_error_history, single_retry_then_timeout
):
    await agent_registry.register("test-id", mock_agent_card)

    with (
        patch(
            "orchestrator.main._route_task",
            new_callable=AsyncMock,
            return_value=_routing_decision(RoutingOutcome.SUITABLE_BUT_BUSY),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await reserve_agent_waiting_if_needed("some task")

    assert exc_info.value.status_code == 503
    assert "A suitable agent exists but none of the suitable agents became available" in exc_info.value.detail
    assert "Last routing justification: Test justification." in exc_info.value.detail


@pytest.mark.asyncio
async def test_reserve_invalid_selected_id_is_treated_like_busy(
    clear_registry, mock_agent_card, mock_error_history, single_retry_then_timeout, caplog
):
    """An unavailable selected ID must not be reserved; the loop retries like the busy case."""
    await agent_registry.register("test-id", mock_agent_card)
    await agent_registry.update_status("test-id", AgentStatus.BUSY)

    with (
        patch(
            "orchestrator.main._route_task",
            new_callable=AsyncMock,
            return_value=_routing_decision(RoutingOutcome.AGENT_SELECTED, "test-id"),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await reserve_agent_waiting_if_needed("some task")

    assert exc_info.value.status_code == 503
    assert "A suitable agent exists but none of the suitable agents became available" in exc_info.value.detail
    assert "invalid or unavailable agent ID 'test-id'" in caplog.text


@pytest.mark.asyncio
async def test_get_agents_info_lists_skills_and_availability_for_every_agent(clear_registry, mock_agent_card):
    reviewer_card = AgentCard(
        name="Reviewer",
        description="Reviews user stories",
        version="1.2.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=[
            AgentSkill(
                id="review-skill",
                name="Jira Requirements Review",
                description="Reviews user stories against requirements",
                tags=["review"],
            )
        ],
        default_input_modes=["text"],
        default_output_modes=["text"],
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url="http://localhost:8001")],
    )
    await agent_registry.register("reviewer-id", reviewer_card)
    await agent_registry.register("worker-id", mock_agent_card)
    await agent_registry.update_status("worker-id", AgentStatus.BUSY)

    info = await _get_agents_info()

    assert "ID: reviewer-id" in info
    assert "ID: worker-id" in info  # busy agents are listed too
    assert "Jira Requirements Review" in info
    assert "Reviews user stories against requirements" in info
    assert "Availability: available" in info
    assert "not available (BUSY)" in info


@pytest.mark.asyncio
async def test_discover_agents_skips_existing(clear_registry, mock_agent_card):
    # Pre-register the agent
    await agent_registry.register("existing-id", mock_agent_card)

    with (
        patch("config.OrchestratorConfig.REMOTE_EXECUTION_AGENT_HOSTS", "http://localhost"),
        patch("config.OrchestratorConfig.AGENT_DISCOVERY_PORTS", "8001-8001"),
        patch("orchestrator.main._fetch_agent_card", return_value=mock_agent_card) as mock_fetch,
        patch("orchestrator.main._check_agent_reachability", return_value=True) as mock_check,
    ):
        await _discover_agents()

        # A known URL is skipped: discovery neither fetches the card nor probes liveness.
        mock_fetch.assert_not_called()
        mock_check.assert_not_called()

        # Verify agent is still there
        assert await agent_registry.contains("existing-id")


@pytest.mark.asyncio
async def test_health_check_unreachable_marks_broken(clear_registry, mock_agent_card):
    await agent_registry.register("existing-id", mock_agent_card)

    with patch("orchestrator.main._check_agent_reachability", return_value=False) as mock_check:
        await _health_check_agents()

        mock_check.assert_called_once_with("http://localhost:8001")

        # Agent is marked BROKEN (OFFLINE), NOT removed.
        assert await agent_registry.contains("existing-id")
        assert await agent_registry.get_status("existing-id") == AgentStatus.BROKEN
        broken_reason, _ = await agent_registry.get_broken_context("existing-id")
        assert broken_reason == BrokenReason.OFFLINE

    # Agent was queued for the recovery worker.
    queued_agent_id, _ = cancellation_queue.get_nowait()
    assert queued_agent_id == "existing-id"


@pytest.mark.asyncio
async def test_health_check_reachable_leaves_available(clear_registry, mock_agent_card):
    await agent_registry.register("existing-id", mock_agent_card)

    with patch("orchestrator.main._check_agent_reachability", return_value=True):
        await _health_check_agents()

        assert await agent_registry.get_status("existing-id") == AgentStatus.AVAILABLE

    assert cancellation_queue.empty()


@pytest.mark.asyncio
async def test_health_check_skips_non_available(clear_registry, mock_agent_card):
    await agent_registry.register("existing-id", mock_agent_card)
    await agent_registry.update_status("existing-id", AgentStatus.BUSY)

    with patch("orchestrator.main._check_agent_reachability", return_value=False) as mock_check:
        await _health_check_agents()

        # BUSY agents are not probed by the health check.
        mock_check.assert_not_called()
        assert await agent_registry.get_status("existing-id") == AgentStatus.BUSY


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
# Registration and manual discovery (WS14)
# =============================================================================


def _card_at(url: str, name: str = "Discovered Agent") -> AgentCard:
    return AgentCard(
        name=name,
        description="Desc",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=[],
        default_input_modes=["text"],
        default_output_modes=["text"],
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url=url)],
    )


@pytest.mark.asyncio
async def test_discovery_registers_an_agent_under_the_url_it_was_reached_on(clear_registry):
    """An agent advertising a loopback URL stays reachable: its card carries the discovered address."""
    with (
        patch("config.OrchestratorConfig.REMOTE_EXECUTION_AGENT_HOSTS", "http://agent-host"),
        patch("config.OrchestratorConfig.AGENT_DISCOVERY_PORTS", "8001-8001"),
        patch("orchestrator.main._fetch_agent_card", return_value=_card_at("http://127.0.0.1:8001")),
    ):
        await _discover_agents()

    agent_id = await agent_registry.get_agent_id_by_url("http://agent-host:8001")
    assert agent_id is not None
    assert await agent_registry.get_discovery_url(agent_id) == "http://agent-host:8001"


@pytest.mark.asyncio
async def test_concurrent_discovery_runs_register_an_agent_once(clear_registry):
    async def _slow_fetch(url):
        await asyncio.sleep(0.01)
        return _card_at(url)

    with (
        patch("config.OrchestratorConfig.REMOTE_EXECUTION_AGENT_HOSTS", "http://agent-host"),
        patch("config.OrchestratorConfig.AGENT_DISCOVERY_PORTS", "8001-8001"),
        patch("orchestrator.main._fetch_agent_card", side_effect=_slow_fetch),
        patch("orchestrator.main._check_agent_reachability", AsyncMock(return_value=True)),
    ):
        await asyncio.gather(_discover_agents(), _run_manual_discovery(), _discover_agents())

    assert len(await agent_registry.get_all_cards()) == 1


@pytest.mark.asyncio
async def test_register_or_refresh_keeps_the_id_and_status_of_a_known_url(clear_registry):
    agent_id = await agent_registry.register_or_refresh("http://agent-host:8001", _card_at("http://agent-host:8001"))
    await agent_registry.update_status(agent_id, AgentStatus.BUSY)

    refreshed_id = await agent_registry.register_or_refresh(
        "http://agent-host:8001", _card_at("http://agent-host:8001", name="Renamed Agent")
    )

    assert refreshed_id == agent_id
    assert await agent_registry.get_status(agent_id) == AgentStatus.BUSY
    assert (await agent_registry.get_card(agent_id)).name == "Renamed Agent"


@pytest.mark.asyncio
async def test_manual_discovery_revives_reachable_and_removes_unreachable_idle_agents(clear_registry):
    await agent_registry.register("up-broken", _card_at("http://agent-host:8001"))
    await agent_registry.update_status("up-broken", AgentStatus.BROKEN, BrokenReason.OFFLINE)
    await agent_registry.register("down-idle", _card_at("http://agent-host:8002"))
    await agent_registry.register("down-busy", _card_at("http://agent-host:8003"))
    await agent_registry.update_status("down-busy", AgentStatus.BUSY)

    with (
        patch("orchestrator.main._discover_new_agents", AsyncMock(return_value=True)),
        patch(
            "orchestrator.main._check_agent_reachability",
            AsyncMock(side_effect=lambda url: url.endswith(":8001")),
        ),
    ):
        report = await _run_manual_discovery()

    assert report == {"message": "1 agents reachable, 1 unreachable agents removed", "reachable": 1, "removed": 1}
    assert await agent_registry.get_status("up-broken") == AgentStatus.AVAILABLE
    assert not await agent_registry.contains("down-idle")
    # A BUSY agent is never removed, even when it does not answer the probe.
    assert await agent_registry.get_status("down-busy") == AgentStatus.BUSY


@pytest.mark.asyncio
async def test_manual_discovery_tolerates_a_failing_probe(clear_registry):
    await agent_registry.register("healthy", _card_at("http://agent-host:8001"))
    await agent_registry.register("crashing", _card_at("http://agent-host:8002"))

    async def _probe(url):
        if url.endswith(":8002"):
            raise RuntimeError("probe crashed")
        return True

    with (
        patch("orchestrator.main._discover_new_agents", AsyncMock(return_value=True)),
        patch("orchestrator.main._check_agent_reachability", AsyncMock(side_effect=_probe)),
    ):
        report = await _run_manual_discovery()

    assert (report["reachable"], report["removed"]) == (1, 1)
    assert await agent_registry.contains("healthy")


@pytest.mark.asyncio
async def test_manual_discovery_reports_that_discovery_is_not_configured(clear_registry):
    with patch("config.OrchestratorConfig.REMOTE_EXECUTION_AGENT_HOSTS", ""):
        report = await _run_manual_discovery()

    assert report["message"].startswith("Agent discovery is not configured")
    assert (report["reachable"], report["removed"]) == (0, 0)


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
    assert consolidated.parts[0].filename == "execution_logs.md"
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

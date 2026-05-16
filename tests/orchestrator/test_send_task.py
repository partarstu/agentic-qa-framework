import asyncio
import contextlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.types import Task, TaskState, TaskStatus as A2ATaskStatus

from orchestrator.main import (
    AgentStatus,
    BrokenReason,
    _retry_cancellation_task,
    _send_task_to_agent,
    cancellation_queue,
)


@pytest.fixture
def mock_registry():
    with patch("orchestrator.main.agent_registry") as mock:
        mock.get_card = AsyncMock()
        mock.update_status = AsyncMock()
        mock.get_name = AsyncMock()
        mock.register = AsyncMock()
        mock.get_status = AsyncMock()
        mock.remove = AsyncMock()
        mock.get_all_cards = AsyncMock()
        mock.is_empty = AsyncMock()
        mock.contains = AsyncMock()
        mock.get_valid_agents = AsyncMock()
        mock.get_broken_context = AsyncMock(return_value=(None, None))
        mock.set_current_task = AsyncMock()
        yield mock


@pytest.mark.asyncio
async def test_send_task_success(mock_registry):
    mock_registry.get_card = AsyncMock(return_value=MagicMock())

    with (
        patch("orchestrator.main.create_client", new_callable=AsyncMock) as mock_create_client,
        patch("orchestrator.main.reserve_agent_waiting_if_needed", new_callable=AsyncMock) as mock_reserve,
    ):
        mock_reserve.return_value = ("agent-1", MagicMock())
        mock_a2a_client = MagicMock()
        mock_create_client.return_value = mock_a2a_client

        real_status = A2ATaskStatus(state=TaskState.TASK_STATE_COMPLETED)
        mock_status_update = MagicMock()
        mock_status_update.task_id = "task-1"
        mock_status_update.status = real_status

        mock_chunk = MagicMock()
        mock_chunk.HasField.side_effect = lambda field: field == "status_update"
        mock_chunk.status_update = mock_status_update

        async def response_generator():
            yield mock_chunk

        mock_a2a_client.send_message.return_value = response_generator()

        task = await _send_task_to_agent("input", "desc")

        assert task.status.state == TaskState.TASK_STATE_COMPLETED
        mock_registry.update_status.assert_any_call("agent-1", AgentStatus.AVAILABLE)


@pytest.mark.asyncio
async def test_send_task_timeout(mock_registry):
    mock_registry.get_card = AsyncMock(return_value=MagicMock())

    with (
        patch("orchestrator.main.create_client", new_callable=AsyncMock) as mock_create_client,
        patch("orchestrator.main.config.OrchestratorConfig.TASK_EXECUTION_TIMEOUT", 0.1),
        patch("orchestrator.main.reserve_agent_waiting_if_needed", new_callable=AsyncMock) as mock_reserve,
    ):
        mock_reserve.return_value = ("agent-1", MagicMock())
        mock_a2a_client = MagicMock()
        mock_create_client.return_value = mock_a2a_client

        # Iterator that sleeps longer than timeout
        async def response_generator():
            await asyncio.sleep(0.5)
            yield MagicMock()

        mock_a2a_client.send_message.return_value = response_generator()

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await _send_task_to_agent("input", "desc")

        assert exc.value.status_code == 408
        broken_calls = [
            c
            for c in mock_registry.update_status.call_args_list
            if len(c.args) >= 2 and c.args[1] == AgentStatus.BROKEN
        ]
        assert len(broken_calls) > 0, "Expected at least one call with AgentStatus.BROKEN"


@pytest.mark.asyncio
async def test_cancellation_task_offline_recovery(mock_registry):
    """Test that OFFLINE agents can be recovered when they respond to card fetch."""
    await cancellation_queue.put(("agent-1", time.time()))

    mock_registry.get_card.return_value = MagicMock()
    mock_registry.get_broken_context.return_value = (BrokenReason.OFFLINE, None)

    with patch("orchestrator.main._fetch_agent_card", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = True

        task = asyncio.create_task(_retry_cancellation_task())

        await asyncio.sleep(0.1)

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        mock_registry.update_status.assert_called_with("agent-1", AgentStatus.AVAILABLE)
        assert cancellation_queue.empty()


@pytest.mark.asyncio
async def test_cancellation_task_retry(mock_registry):
    """Test that agents that fail recovery check are re-queued for retry."""
    await cancellation_queue.put(("agent-1", time.time()))

    mock_registry.get_card.return_value = MagicMock()
    mock_registry.get_broken_context.return_value = (BrokenReason.OFFLINE, None)

    with patch("orchestrator.main._fetch_agent_card", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = False

        task = asyncio.create_task(_retry_cancellation_task())

        await asyncio.sleep(0.1)

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        available_calls = [
            c
            for c in mock_registry.update_status.call_args_list
            if len(c.args) >= 2 and c.args[1] == AgentStatus.AVAILABLE
        ]
        assert len(available_calls) == 0, "Agent should not be marked AVAILABLE when still offline"


@pytest.mark.asyncio
async def test_cancellation_task_stuck_with_cancel(mock_registry):
    """Test that TASK_STUCK agents trigger task cancellation before recovery."""
    await cancellation_queue.put(("agent-1", time.time()))

    mock_registry.get_card.return_value = MagicMock()
    mock_registry.get_broken_context.return_value = (BrokenReason.TASK_STUCK, "task-123")

    with patch("orchestrator.main._cancel_agent_task", new_callable=AsyncMock) as mock_cancel:
        mock_cancel.return_value = True

        task = asyncio.create_task(_retry_cancellation_task())

        await asyncio.sleep(0.1)

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        mock_cancel.assert_called_once()
        mock_registry.update_status.assert_called_with("agent-1", AgentStatus.AVAILABLE)

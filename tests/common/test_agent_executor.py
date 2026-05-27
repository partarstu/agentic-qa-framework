# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
import contextlib
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.server.agent_execution import RequestContext
from a2a.types import Message, TaskState, TaskStatusUpdateEvent, TaskArtifactUpdateEvent

from common.agent_executor import DefaultAgentExecutor
from common.agent_log_capture import AgentLogCaptureHandler
from common.streaming import current_log_handler


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.run = AsyncMock()
    agent._activity_queue = asyncio.Queue()
    return agent


@pytest.fixture
def mock_context():
    context = MagicMock(spec=RequestContext)
    context.task_id = "test-task-123"
    context.context_id = "test-context-123"
    context.current_task = MagicMock()
    return context


@pytest.fixture
def mock_event_queue():
    queue = MagicMock()
    queue.enqueue_event = AsyncMock()
    return queue


# ---------------------------------------------------------------------------
# execute() — success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_success(mock_agent, mock_context, mock_event_queue):
    executor = DefaultAgentExecutor(mock_agent)

    # Mock message
    mock_message = MagicMock(spec=Message)
    mock_context.message = mock_message

    # Mock result
    mock_result = MagicMock()
    mock_result.parts = []
    mock_agent.run.return_value = mock_result

    await executor.execute(mock_context, mock_event_queue)

    # Check agent run
    mock_agent.run.assert_called_once_with(mock_message)

    # Event order: Task object, WORKING status, result artifact, COMPLETED status
    assert mock_event_queue.enqueue_event.call_count == 4

    calls = mock_event_queue.enqueue_event.call_args_list
    assert isinstance(calls[1][0][0], TaskStatusUpdateEvent)
    assert calls[1][0][0].status.state == TaskState.TASK_STATE_WORKING

    assert isinstance(calls[2][0][0], TaskArtifactUpdateEvent)
    assert calls[2][0][0].artifact.name == "agent_execution_result"

    assert isinstance(calls[3][0][0], TaskStatusUpdateEvent)
    assert calls[3][0][0].status.state == TaskState.TASK_STATE_COMPLETED


@pytest.mark.asyncio
async def test_execute_no_message(mock_agent, mock_context, mock_event_queue):
    executor = DefaultAgentExecutor(mock_agent)
    mock_context.message = None

    await executor.execute(mock_context, mock_event_queue)

    mock_agent.run.assert_not_called()

    # ValueError raised before Task is enqueued → only 1 event (FAILED status)
    assert mock_event_queue.enqueue_event.call_count == 1
    call = mock_event_queue.enqueue_event.call_args[0][0]
    assert isinstance(call, TaskStatusUpdateEvent)
    assert call.status.state == TaskState.TASK_STATE_FAILED
    assert "No message found" in str(call.status.message)


@pytest.mark.asyncio
async def test_execute_agent_failure(mock_agent, mock_context, mock_event_queue):
    executor = DefaultAgentExecutor(mock_agent)
    mock_context.message = MagicMock()

    mock_agent.run.side_effect = Exception("Agent crashed")

    await executor.execute(mock_context, mock_event_queue)

    # Event order: Task object, WORKING status, FAILED status
    assert mock_event_queue.enqueue_event.call_count == 3

    calls = mock_event_queue.enqueue_event.call_args_list
    assert isinstance(calls[2][0][0], TaskStatusUpdateEvent)
    assert calls[2][0][0].status.state == TaskState.TASK_STATE_FAILED
    assert "Agent crashed" in str(calls[2][0][0].status.message)


# ---------------------------------------------------------------------------
# cancel()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_emits_canceled_on_original_queue(mock_agent, mock_context, mock_event_queue):
    executor = DefaultAgentExecutor(mock_agent)
    mock_context.message = MagicMock()

    running_event = asyncio.Event()

    async def slow_run(_message):
        running_event.set()
        await asyncio.sleep(100)

    mock_agent.run.side_effect = slow_run

    execute_task = asyncio.create_task(executor.execute(mock_context, mock_event_queue))
    await running_event.wait()

    cancel_queue = MagicMock()
    cancel_queue.enqueue_event = AsyncMock()
    cancel_context = MagicMock(spec=RequestContext)
    cancel_context.task_id = mock_context.task_id
    cancel_context.context_id = mock_context.context_id

    await executor.cancel(cancel_context, cancel_queue)

    with contextlib.suppress(asyncio.CancelledError):
        await execute_task

    canceled_on_original = [
        call[0][0]
        for call in mock_event_queue.enqueue_event.call_args_list
        if isinstance(call[0][0], TaskStatusUpdateEvent)
        and call[0][0].status.state == TaskState.TASK_STATE_CANCELED
    ]
    assert len(canceled_on_original) == 1
    cancel_queue.enqueue_event.assert_not_called()
    assert executor._active_runs == {}


@pytest.mark.asyncio
async def test_cancel_unknown_task_id_emits_on_cancel_queue(mock_context, mock_event_queue):
    executor = DefaultAgentExecutor(MagicMock())

    cancel_queue = MagicMock()
    cancel_queue.enqueue_event = AsyncMock()

    await executor.cancel(mock_context, cancel_queue)

    calls = cancel_queue.enqueue_event.call_args_list
    assert len(calls) == 1
    event = calls[0][0][0]
    assert isinstance(event, TaskStatusUpdateEvent)
    assert event.status.state == TaskState.TASK_STATE_CANCELED
    mock_event_queue.enqueue_event.assert_not_called()


# ---------------------------------------------------------------------------
# ContextVars
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contextvars_set_during_run_and_reset_after(mock_agent, mock_context, mock_event_queue):
    executor = DefaultAgentExecutor(mock_agent)
    mock_context.message = MagicMock()

    handler_during_run = None

    async def capture_context(_message):
        nonlocal handler_during_run
        handler_during_run = current_log_handler.get()
        result = MagicMock()
        result.parts = []
        return result

    mock_agent.run.side_effect = capture_context

    await executor.execute(mock_context, mock_event_queue)

    assert isinstance(handler_during_run, AgentLogCaptureHandler)
    assert current_log_handler.get() is None


# ---------------------------------------------------------------------------
# Final log drain and TaskUpdater events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_final_drain_emits_remaining_log_batch(mock_agent, mock_context, mock_event_queue):
    """Logs remaining after agent.run appear in a logs artifact chunk with last_chunk=True."""
    executor = DefaultAgentExecutor(mock_agent)
    mock_context.message = MagicMock()

    mock_result = MagicMock()
    mock_result.parts = []
    mock_agent.run.return_value = mock_result

    with patch("common.agent_executor.AgentLogCaptureHandler") as MockHandlerCls:
        mock_handler = MockHandlerCls.return_value
        mock_handler.level = logging.NOTSET
        mock_handler.setLevel = MagicMock()
        mock_handler.drain.return_value = ["captured log line"]

        with patch("common.agent_executor._LOG_FLUSH_INTERVAL_SECONDS", 100):
            await executor.execute(mock_context, mock_event_queue)

    log_stream_calls = [
        call[0][0]
        for call in mock_event_queue.enqueue_event.call_args_list
        if isinstance(call[0][0], TaskArtifactUpdateEvent)
        and call[0][0].artifact.name == "logs"
    ]
    assert len(log_stream_calls) == 1
    artifact_event = log_stream_calls[0]
    assert artifact_event.last_chunk is True
    assert artifact_event.append is False
    assert len(artifact_event.artifact.parts) == 1
    assert artifact_event.artifact.parts[0].raw == b"captured log line"

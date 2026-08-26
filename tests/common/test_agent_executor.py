# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
import contextlib
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.server.agent_execution import RequestContext
from a2a.types import Message, TaskArtifactUpdateEvent, TaskState, TaskStatusUpdateEvent

from common.agent_executor import DefaultAgentExecutor
from common.agent_log_capture import AgentLogCaptureHandler
from common.streaming import current_log_handler


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.run = AsyncMock()
    queue = asyncio.Queue()
    agent._activity_queue = queue
    agent.activity_queue = queue
    # Real agents start with no captured usage; the executor only emits a usage
    # artifact when this is set, so default to None to mirror that contract.
    agent.latest_token_usage = None
    agent.model_name = "openai:test-model"
    agent.version = "2.5"
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
async def test_execute_emits_usage_artifact(mock_agent, mock_context, mock_event_queue):
    """When the agent captured token usage, a usage artifact is emitted before completion."""
    from common.token_usage import TokenUsage

    executor = DefaultAgentExecutor(mock_agent)
    mock_context.message = MagicMock(spec=Message)

    usage = TokenUsage(
        model_name="openai:test-model",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        cache_read_tokens=0,
        requests=1,
        tool_calls=2,
        cost_usd=0.0012,
    )

    # Mirror AgentBase.run, which populates latest_token_usage during the run (the executor
    # resets it to None at task start, so it must be set from within run()).
    async def run_and_capture_usage(_message):
        mock_agent.latest_token_usage = usage
        result = MagicMock()
        result.parts = []
        return result

    mock_agent.run.side_effect = run_and_capture_usage

    await executor.execute(mock_context, mock_event_queue)

    usage_artifacts = [
        call[0][0]
        for call in mock_event_queue.enqueue_event.call_args_list
        if isinstance(call[0][0], TaskArtifactUpdateEvent) and call[0][0].artifact.name == "agent_usage"
    ]
    assert len(usage_artifacts) == 1
    payload = TokenUsage.model_validate_json(usage_artifacts[0].artifact.parts[0].raw.decode("utf-8"))
    assert payload.total_tokens == 150
    assert payload.cost_usd == 0.0012


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
        if isinstance(call[0][0], TaskStatusUpdateEvent) and call[0][0].status.state == TaskState.TASK_STATE_CANCELED
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
        if isinstance(call[0][0], TaskArtifactUpdateEvent) and call[0][0].artifact.name == "logs"
    ]
    assert len(log_stream_calls) == 1
    artifact_event = log_stream_calls[0]
    assert artifact_event.last_chunk is True
    assert artifact_event.append is False
    assert len(artifact_event.artifact.parts) == 1
    assert artifact_event.artifact.parts[0].raw == b"captured log line"


@pytest.mark.asyncio
async def test_concurrent_execute_lock(mock_agent, mock_event_queue):
    executor = DefaultAgentExecutor(mock_agent)
    execution_order = []

    async def slow_run(_message):
        execution_order.append("start")
        await asyncio.sleep(0.05)
        execution_order.append("end")
        mock_result = MagicMock()
        mock_result.parts = []
        return mock_result

    mock_agent.run.side_effect = slow_run

    context1 = MagicMock(spec=RequestContext)
    context1.task_id = "task-1"
    context1.context_id = "context-1"
    context1.current_task = MagicMock()
    context1.message = MagicMock()

    context2 = MagicMock(spec=RequestContext)
    context2.task_id = "task-2"
    context2.context_id = "context-2"
    context2.current_task = MagicMock()
    context2.message = MagicMock()

    task1 = asyncio.create_task(executor.execute(context1, mock_event_queue))
    task2 = asyncio.create_task(executor.execute(context2, mock_event_queue))

    await asyncio.gather(task1, task2)

    assert execution_order == ["start", "end", "start", "end"]


@pytest.mark.asyncio
async def test_flush_activity_loop_update_status_failure(mock_agent, mock_context, mock_event_queue):
    executor = DefaultAgentExecutor(mock_agent)
    mock_context.message = MagicMock()

    mock_updater = MagicMock()
    mock_updater.update_status = AsyncMock(side_effect=[Exception("Transient error"), None])
    mock_updater.start_work = AsyncMock()
    mock_updater.add_artifact = AsyncMock()
    mock_updater.complete = AsyncMock()

    async def run_agent(_message):
        await mock_agent.activity_queue.put("activity 1")
        await mock_agent.activity_queue.put("activity 2")
        await asyncio.sleep(0.02)
        mock_result = MagicMock()
        mock_result.parts = []
        return mock_result

    mock_agent.run.side_effect = run_agent

    with patch("common.agent_executor.TaskUpdater", return_value=mock_updater):
        await executor.execute(mock_context, mock_event_queue)

    assert mock_updater.update_status.call_count == 2


@pytest.mark.asyncio
async def test_execute_cancelled_swallowed_and_emits_canceled_event(mock_agent, mock_context, mock_event_queue):
    executor = DefaultAgentExecutor(mock_agent)
    mock_context.message = MagicMock()

    async def running_run(_message):
        await asyncio.sleep(100)

    mock_agent.run.side_effect = running_run

    execute_task = asyncio.create_task(executor.execute(mock_context, mock_event_queue))
    await asyncio.sleep(0.01)

    await executor.cancel(mock_context, mock_event_queue)
    await execute_task

    calls = mock_event_queue.enqueue_event.call_args_list
    canceled_calls = [
        call[0][0] for call in calls
        if isinstance(call[0][0], TaskStatusUpdateEvent) and call[0][0].status.state == TaskState.TASK_STATE_CANCELED
    ]
    assert len(canceled_calls) == 1


@pytest.mark.asyncio
async def test_task_start_log_names_model_and_agent_version(
    mock_agent, mock_context, mock_event_queue, caplog
):
    """Every task start must be traceable to the agent version and the model that served it."""
    executor = DefaultAgentExecutor(mock_agent)
    mock_context.message = MagicMock(spec=Message)
    mock_result = MagicMock()
    mock_result.parts = []
    mock_agent.run.return_value = mock_result

    with caplog.at_level(logging.INFO, logger="agent_executor"):
        await executor.execute(mock_context, mock_event_queue)

    start_records = [r for r in caplog.records if r.message.startswith("Executing task")]
    assert start_records, f"No task-start record was emitted. Records: {caplog.text}"
    assert "openai:test-model" in start_records[0].message
    assert "2.5" in start_records[0].message

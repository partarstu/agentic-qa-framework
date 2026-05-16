from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.server.agent_execution import RequestContext
from a2a.types import Message, Task, TaskArtifactUpdateEvent, TaskState, TaskStatusUpdateEvent

from common.agent_executor import DefaultAgentExecutor


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.run = AsyncMock()
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

    # Event order: Task object, Working status, Artifact update, Completed status
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

    # ValueError raised before Task is enqueued → only 1 event (Failed status)
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

    # Event order: Task object, Working status, Failed status
    assert mock_event_queue.enqueue_event.call_count == 3

    calls = mock_event_queue.enqueue_event.call_args_list
    assert isinstance(calls[2][0][0], TaskStatusUpdateEvent)
    assert calls[2][0][0].status.state == TaskState.TASK_STATE_FAILED
    assert "Agent crashed" in str(calls[2][0][0].status.message)

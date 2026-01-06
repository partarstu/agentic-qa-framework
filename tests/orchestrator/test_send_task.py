
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from orchestrator.main import _send_task_to_agent, _retry_cancellation_task, cancellation_queue, AgentStatus, BrokenReason
from a2a.types import TaskState, TaskStatus, Task, JSONRPCErrorResponse, Message
import asyncio
import time

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
        yield mock

@pytest.mark.asyncio
async def test_send_task_success(mock_registry):
    mock_registry.get_card = AsyncMock(return_value=MagicMock())
    
    with patch("orchestrator.main.httpx.AsyncClient") as mock_client_cls, \
         patch("orchestrator.main.ClientFactory") as mock_factory_cls:
         
        mock_a2a_client = MagicMock()
        mock_factory_cls.return_value.create.return_value = mock_a2a_client
        
        # Mock iterator response
        async def response_generator():
            task = MagicMock()
            task.status.state = TaskState.completed
            yield (task, None)

        mock_a2a_client.send_message.return_value = response_generator()
        
        task = await _send_task_to_agent("agent-1", "input", "desc")
        
        assert task.status.state == TaskState.completed
        mock_registry.update_status.assert_any_call("agent-1", AgentStatus.BUSY)
        mock_registry.update_status.assert_any_call("agent-1", AgentStatus.AVAILABLE)

@pytest.mark.asyncio
async def test_send_task_timeout(mock_registry):
    mock_registry.get_card = AsyncMock(return_value=MagicMock())
    
    with patch("orchestrator.main.httpx.AsyncClient"), \
         patch("orchestrator.main.ClientFactory") as mock_factory_cls, \
         patch("orchestrator.main.config.OrchestratorConfig.TASK_EXECUTION_TIMEOUT", 0.1):
         
        mock_a2a_client = MagicMock()
        mock_factory_cls.return_value.create.return_value = mock_a2a_client
        
        # Iterator that sleeps longer than timeout
        async def response_generator():
            await asyncio.sleep(0.5)
            yield MagicMock()
            
        mock_a2a_client.send_message.return_value = response_generator()
        
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await _send_task_to_agent("agent-1", "input", "desc")
        
        assert exc.value.status_code == 408
        # Check that update_status was called with BROKEN status and TASK_STUCK reason
        # The call should include agent_id, status, broken_reason, and optionally stuck_task_id
        broken_calls = [c for c in mock_registry.update_status.call_args_list 
                        if len(c.args) >= 2 and c.args[1] == AgentStatus.BROKEN]
        assert len(broken_calls) > 0, "Expected at least one call with AgentStatus.BROKEN"

@pytest.mark.asyncio
async def test_cancellation_task_offline_recovery(mock_registry):
    """Test that OFFLINE agents can be recovered when they respond to card fetch."""
    # Setup queue with one item
    await cancellation_queue.put(("agent-1", time.time()))
    
    mock_registry.get_card.return_value = MagicMock(url="http://agent")
    # Simulate OFFLINE agent
    mock_registry.get_broken_context.return_value = (BrokenReason.OFFLINE, None)
    
    # Mock _fetch_agent_card to return success (agent is back online)
    with patch("orchestrator.main._fetch_agent_card", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = True
        
        # Run _retry_cancellation_task in a task, then cancel it
        task = asyncio.create_task(_retry_cancellation_task())
        
        # Wait for queue processing
        await asyncio.sleep(0.1)
        
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
            
        mock_registry.update_status.assert_called_with("agent-1", AgentStatus.AVAILABLE)
        assert cancellation_queue.empty()

@pytest.mark.asyncio
async def test_cancellation_task_retry(mock_registry):
    """Test that agents that fail recovery check are re-queued for retry."""
    # Setup queue
    await cancellation_queue.put(("agent-1", time.time()))
    
    mock_registry.get_card.return_value = MagicMock(url="http://agent")
    # Simulate OFFLINE agent that is still offline
    mock_registry.get_broken_context.return_value = (BrokenReason.OFFLINE, None)
    
    # Mock _fetch_agent_card to return False (still offline)
    with patch("orchestrator.main._fetch_agent_card", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = False
        
        task = asyncio.create_task(_retry_cancellation_task())
        
        await asyncio.sleep(0.1)
        
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        # Agent should not be marked as AVAILABLE since it's still offline
        available_calls = [c for c in mock_registry.update_status.call_args_list 
                          if len(c.args) >= 2 and c.args[1] == AgentStatus.AVAILABLE]
        assert len(available_calls) == 0, "Agent should not be marked AVAILABLE when still offline"


@pytest.mark.asyncio
async def test_cancellation_task_stuck_with_cancel(mock_registry):
    """Test that TASK_STUCK agents trigger task cancellation before recovery."""
    # Setup queue
    await cancellation_queue.put(("agent-1", time.time()))
    
    mock_registry.get_card.return_value = MagicMock(url="http://agent")
    # Simulate TASK_STUCK agent with a known task ID
    mock_registry.get_broken_context.return_value = (BrokenReason.TASK_STUCK, "task-123")
    
    with patch("orchestrator.main._cancel_agent_task", new_callable=AsyncMock) as mock_cancel:
        mock_cancel.return_value = True  # Cancellation succeeds
        
        task = asyncio.create_task(_retry_cancellation_task())
        
        await asyncio.sleep(0.1)
        
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        # Should have attempted to cancel the stuck task
        mock_cancel.assert_called_once()
        mock_registry.update_status.assert_called_with("agent-1", AgentStatus.AVAILABLE)


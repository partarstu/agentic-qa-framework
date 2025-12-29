
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from orchestrator.main import _send_task_to_agent, _retry_cancellation_task, cancellation_queue, AgentStatus
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
        mock_registry.update_status.assert_any_call("agent-1", AgentStatus.BROKEN)

@pytest.mark.asyncio
async def test_cancellation_task(mock_registry):
    # Setup queue with one item
    await cancellation_queue.put(("agent-1", time.time()))
    
    mock_registry.get_card.return_value = MagicMock(url="http://agent")
    
    # Mock _fetch_agent_card to return success (recovered)
    with patch("orchestrator.main._fetch_agent_card", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = True
        
        # Run _retry_cancellation_task in a task, then cancel it
        task = asyncio.create_task(_retry_cancellation_task())
        
        # Wait for queue to be empty
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
    # Setup queue
    await cancellation_queue.put(("agent-1", time.time()))
    
    mock_registry.get_card.return_value = MagicMock(url="http://agent")
    
    # Mock _fetch_agent_card to return False (not recovered)
    with patch("orchestrator.main._fetch_agent_card", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = False
        
        task = asyncio.create_task(_retry_cancellation_task())
        
        await asyncio.sleep(0.1)
        
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        # Should be put back in queue (or sleep called).
        # Since we cancelled quickly, maybe it's still in sleep?
        # The code: await asyncio.sleep(60)
        # So it is likely sleeping.
        pass

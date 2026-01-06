
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from execute_test_case import load_test_case, send_test_case_to_agent, main
from common.models import TestCase
from a2a.types import TaskState, TaskStatus, Task

@pytest.mark.asyncio
async def test_load_test_case_success():
    with patch("execute_test_case.get_test_management_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        mock_tc = TestCase(
            key="TC-1", summary="S", name="N", steps=[], test_data=[], expected_results=[], 
            labels=[], comment="", preconditions="", parent_issue_key="P"
        )
        mock_client.fetch_test_case_by_key.return_value = mock_tc
        
        tc = await load_test_case("TC-1")
        assert tc.key == "TC-1"

@pytest.mark.asyncio
async def test_load_test_case_not_found():
    with patch("execute_test_case.get_test_management_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.fetch_test_case_by_key.return_value = None
        
        with pytest.raises(Exception):
            await load_test_case("TC-1")

@pytest.mark.asyncio
async def test_send_test_case_to_agent_success():
    test_case = TestCase(
        key="TC-1", summary="S", name="N", steps=[], test_data=[], expected_results=[], 
        labels=[], comment="", preconditions="", parent_issue_key="P"
    )
    
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        
        # Mock client factory and a2a client
        # send_test_case_to_agent creates ClientFactory internally
        # We need to mock ClientFactory
        
        with patch("execute_test_case.ClientFactory") as mock_factory_cls:
            mock_factory = MagicMock()
            mock_factory_cls.return_value = mock_factory
            mock_a2a_client = MagicMock()
            mock_factory.create.return_value = mock_a2a_client
            
            # Mock iterator
            mock_task = MagicMock(spec=Task)
            mock_task.status = TaskStatus(state=TaskState.completed)
            mock_task.artifacts = []
            
            async def async_iter():
                yield (mock_task, None)
            
            mock_a2a_client.send_message.return_value = async_iter()
            
            await send_test_case_to_agent(8000, test_case)
            
            # Check logs? We assume success if no exception and it ran through

@pytest.mark.asyncio
async def test_main_execution():
    with patch("argparse.ArgumentParser.parse_args") as mock_args, \
         patch("execute_test_case.load_test_case", new_callable=AsyncMock) as mock_load, \
         patch("execute_test_case.send_test_case_to_agent", new_callable=AsyncMock) as mock_send:
         
         mock_args.return_value = MagicMock(test_case_key="TC-1", agent_port=8000)
         mock_load.return_value = MagicMock()
         
         await main()
         
         mock_load.assert_called_with("TC-1")
         mock_send.assert_called_once()

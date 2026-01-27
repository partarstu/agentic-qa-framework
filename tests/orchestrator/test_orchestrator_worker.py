
import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.types import Artifact, TaskState, TaskStatus, TextPart

from common.models import TestCase, TestExecutionResult
from orchestrator.main import AgentStatus, _agent_worker, _execute_single_test


@pytest.fixture
def mock_registry():
    with patch("orchestrator.main.agent_registry") as mock:
        mock.get_name = AsyncMock(return_value="Agent 1")
        mock.get_status = AsyncMock(return_value=AgentStatus.AVAILABLE)
        yield mock

@pytest.fixture
def mock_queue():
    queue = MagicMock()
    queue.get = AsyncMock()
    queue.task_done = MagicMock()
    queue.put_nowait = MagicMock()
    return queue

@pytest.mark.asyncio
async def test_agent_worker_success(mock_registry, mock_queue):
    mock_registry.get_status.side_effect = [AgentStatus.AVAILABLE, AgentStatus.AVAILABLE]

    test_case = TestCase(
        key="TC-1",
        summary="Sum",
        name="Name",
        steps=[],
        test_data=[],
        expected_results=[],
        labels=[],
        comment="",
        preconditions="",
        parent_issue_key="STORY-1"
    )
    mock_queue.get.side_effect = [(test_case, "UI"), asyncio.CancelledError]

    with patch("orchestrator.main._execute_single_test", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = TestExecutionResult(
            stepResults=[], testCaseKey="TC-1", testCaseName="Name",
            testExecutionStatus="passed", generalErrorMessage="",
            start_timestamp="now", end_timestamp="then"
        )

        results = []
        with contextlib.suppress(asyncio.CancelledError):
            await _agent_worker("agent-1", mock_queue, results, ["agent-1"])

        assert len(results) == 1
        mock_exec.assert_called_once()
        mock_registry.get_status.assert_called()

@pytest.mark.asyncio
async def test_agent_worker_broken(mock_registry, mock_queue):
    mock_registry.get_status.return_value = AgentStatus.BROKEN
    results = []
    await _agent_worker("agent-1", mock_queue, results, ["agent-1"])
    assert len(results) == 0

@pytest.mark.asyncio
async def test_execute_single_test_success(mock_registry):
    test_case = TestCase(
        key="TC-1",
        summary="Sum",
        name="Name",
        steps=[],
        test_data=[],
        expected_results=[],
        labels=[],
        comment="",
        preconditions="",
        parent_issue_key="STORY-1"
    )

    mock_task = MagicMock()
    mock_task.status.state = TaskState.completed
    mock_task.artifacts = [
        Artifact(artifactId="a1", parts=[TextPart(text='{"testExecutionStatus": "passed"}')])
    ]

    mock_registry.get_name.return_value = "Agent 1"

    with patch("orchestrator.main._send_task_to_agent", new_callable=AsyncMock) as mock_send, \
         patch("orchestrator.main._get_results_extractor_agent") as mock_extractor_agent_cls:

        mock_send.return_value = mock_task

        mock_extractor_instance = MagicMock()
        mock_extractor_agent_cls.return_value = mock_extractor_instance

        mock_run_result = MagicMock()
        mock_run_result.output = TestExecutionResult(
            stepResults=[], testCaseKey="TC-1", testCaseName="Name",
            testExecutionStatus="passed", generalErrorMessage="",
            start_timestamp="now", end_timestamp="then"
        )
        mock_extractor_instance.run = AsyncMock(return_value=mock_run_result)

        result = await _execute_single_test("agent-1", test_case, "UI")

        assert result.testExecutionStatus == "passed"
        assert result.testCaseKey == "TC-1"


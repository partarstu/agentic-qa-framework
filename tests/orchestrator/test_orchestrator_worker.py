# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.types import TaskState

from common.models import TestCase, TestExecutionResult
from orchestrator.main import (
    AgentStatus,
    BrokenReason,
    _agent_worker,
    _execute_single_test,
    _execute_test_group,
)
from tests.orchestrator.conftest import agent_card


def _test_case(key: str = "TC-1") -> TestCase:
    return TestCase(
        key=key,
        summary="Sum",
        name="Name",
        steps=[],
        labels=[],
        comment="",
        preconditions="",
        parent_issue_key="STORY-1",
    )


@pytest.fixture
def mock_registry():
    with patch("orchestrator.main.agent_registry") as mock:
        mock.get_name = AsyncMock(return_value="Agent 1")
        mock.get_status = AsyncMock(return_value=AgentStatus.AVAILABLE)
        mock.get_card = AsyncMock(return_value=agent_card())
        mock.get_broken_context = AsyncMock(return_value=(None, None))
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
        parent_issue_key="STORY-1",
    )
    mock_queue.get.side_effect = [(test_case, "UI"), asyncio.CancelledError]

    with patch("orchestrator.main._execute_single_test", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = TestExecutionResult(
            stepResults=[],
            testCaseKey="TC-1",
            testCaseName="Name",
            testExecutionStatus="passed",
            generalErrorMessage="",
            start_timestamp="now",
            end_timestamp="then",
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
async def test_agent_worker_enqueues_recovery_when_task_fails(mock_registry, mock_queue):
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
        parent_issue_key="STORY-1",
    )
    mock_queue.get.side_effect = [(test_case, "UI")]
    mock_registry.update_status = AsyncMock()

    with (
        patch("orchestrator.main._execute_single_test", new_callable=AsyncMock) as mock_exec,
        patch("orchestrator.main.cancellation_queue") as mock_cancellation_queue,
    ):
        mock_exec.side_effect = RuntimeError("iterator finished before completion")
        mock_cancellation_queue.put = AsyncMock()

        results = []
        await _agent_worker("agent-1", mock_queue, results, ["agent-1"])

        mock_registry.update_status.assert_awaited_with(
            "agent-1", AgentStatus.BROKEN, BrokenReason.TASK_STUCK
        )
        mock_cancellation_queue.put.assert_awaited_once()
        enqueued_agent_id, _ = mock_cancellation_queue.put.await_args.args[0]
        assert enqueued_agent_id == "agent-1"


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
        parent_issue_key="STORY-1",
    )

    mock_task = MagicMock()
    mock_task.status.state = TaskState.TASK_STATE_COMPLETED

    mock_part = MagicMock()
    mock_part.HasField.side_effect = lambda field: field == "text"
    mock_part.text = '{"testExecutionStatus": "passed"}'
    mock_artifact = MagicMock()
    mock_artifact.parts = [mock_part]
    mock_task.artifacts = [mock_artifact]

    mock_registry.get_name.return_value = "Agent 1"

    with (
        patch("orchestrator.main._send_task_to_agent", new_callable=AsyncMock) as mock_send,
        patch("orchestrator.main._get_results_extractor_agent") as mock_extractor_agent_cls,
    ):
        mock_send.return_value = mock_task

        mock_extractor_instance = MagicMock()
        mock_extractor_agent_cls.return_value = mock_extractor_instance

        mock_run_result = MagicMock()
        mock_run_result.output = TestExecutionResult(
            stepResults=[],
            testCaseKey="TC-1",
            testCaseName="Name",
            testExecutionStatus="passed",
            generalErrorMessage="",
            start_timestamp="now",
            end_timestamp="then",
        )
        mock_extractor_instance.run = AsyncMock(return_value=mock_run_result)

        result = await _execute_single_test("agent-1", test_case, "UI")

        assert result.testExecutionStatus == "passed"
        assert result.testCaseKey == "TC-1"


@pytest.mark.asyncio
async def test_agent_worker_keeps_stuck_task_id_when_agent_is_already_broken(mock_registry, mock_queue):
    """The send path already marked the agent BROKEN with a stuck task id - the worker must not overwrite it."""
    mock_queue.get.side_effect = [(_test_case(), "UI")]
    mock_registry.get_status = AsyncMock(side_effect=[AgentStatus.AVAILABLE, AgentStatus.BROKEN])
    mock_registry.update_status = AsyncMock()
    mock_registry.get_broken_context = AsyncMock(return_value=(BrokenReason.TASK_STUCK, "stuck-task-1"))

    with (
        patch("orchestrator.main._execute_single_test", new_callable=AsyncMock) as mock_exec,
        patch("orchestrator.main.cancellation_queue") as mock_cancellation_queue,
    ):
        mock_exec.side_effect = RuntimeError("iterator finished before completion")
        mock_cancellation_queue.put = AsyncMock()

        await _agent_worker("agent-1", mock_queue, [], ["agent-1"])

        mock_registry.update_status.assert_not_awaited()
        mock_cancellation_queue.put.assert_not_awaited()
        reason, stuck_task_id = await mock_registry.get_broken_context("agent-1")
        assert (reason, stuck_task_id) == (BrokenReason.TASK_STUCK, "stuck-task-1")


@pytest.mark.asyncio
async def test_agent_worker_requeues_and_leaves_cancellation_to_the_recovery_task(mock_registry, mock_queue):
    """With another agent alive the case is re-queued; freeing the stuck task is the recovery task's job."""
    test_case = _test_case()
    mock_queue.get.side_effect = [(test_case, "UI")]
    mock_registry.get_status = AsyncMock(
        side_effect=[AgentStatus.AVAILABLE, AgentStatus.BROKEN, AgentStatus.AVAILABLE]
    )
    mock_registry.update_status = AsyncMock()
    mock_registry.get_broken_context = AsyncMock(return_value=(BrokenReason.TASK_STUCK, "stuck-task-1"))

    with (
        patch("orchestrator.main._execute_single_test", new_callable=AsyncMock) as mock_exec,
        patch("orchestrator.main.cancellation_queue") as mock_cancellation_queue,
        patch("orchestrator.main._cancel_agent_task", new_callable=AsyncMock) as mock_cancel,
    ):
        mock_exec.side_effect = RuntimeError("iterator finished before completion")
        mock_cancellation_queue.put = AsyncMock()

        results = []
        await _agent_worker("agent-1", mock_queue, results, ["agent-1", "agent-2"])
        await asyncio.sleep(0)

        mock_cancel.assert_not_awaited()
        mock_queue.put_nowait.assert_called_once_with((test_case, "UI"))
        assert results == []


@pytest.mark.asyncio
async def test_execute_test_group_spawns_one_worker_per_test_case(mock_registry):
    """Agents beyond the number of test cases get no worker, but stay in the pool as failover targets."""
    mock_registry.contains = AsyncMock(return_value=True)
    test_cases = [_test_case("TC-1"), _test_case("TC-2")]
    all_agent_ids = ["a-1", "a-2", "a-3", "a-4", "a-5"]
    started_agent_ids: list[str] = []
    seen_pools: list[list[str]] = []

    async def _drain_queue(agent_id, queue, results, pool_agent_ids):
        """Stand-in worker that only consumes the queue, so _execute_test_group can finish."""
        started_agent_ids.append(agent_id)
        seen_pools.append(pool_agent_ids)
        while await queue.get() is not None:
            queue.task_done()
        queue.task_done()

    with patch("orchestrator.main._agent_worker", _drain_queue):
        await asyncio.wait_for(_execute_test_group("UI", test_cases, all_agent_ids), timeout=5)

    assert started_agent_ids == ["a-1", "a-2"]
    assert seen_pools == [all_agent_ids, all_agent_ids]

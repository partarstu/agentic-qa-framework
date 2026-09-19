# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.types import TaskState
from fastapi import HTTPException

from common.models import TestCase, TestExecutionResult
from orchestrator.main import (
    AgentStatus,
    BrokenReason,
    _agent_worker,
    _execute_single_test,
    _execute_test_group,
    _generate_test_report,
    _request_incident_creation_for_failed_tests,
    _send_task_to_agent_with_message,
)
from orchestrator.models import TaskStatus
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

        mock_registry.update_status.assert_awaited_with("agent-1", AgentStatus.BROKEN, BrokenReason.TASK_STUCK)
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
    mock_registry.get_status = AsyncMock(side_effect=[AgentStatus.AVAILABLE, AgentStatus.BROKEN, AgentStatus.AVAILABLE])
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


@pytest.mark.asyncio
async def test_execute_test_group_reports_unexecuted_cases_when_every_worker_exits(mock_registry):
    """WS15: once no worker is left, the group finishes and reports the queued cases as errors instead of hanging."""
    mock_registry.contains = AsyncMock(return_value=True)

    async def _exit_at_once(agent_id, queue, results, pool_agent_ids):
        """Stand-in for a worker whose agent broke before it took any test case."""

    with patch("orchestrator.main._agent_worker", _exit_at_once):
        results = await asyncio.wait_for(
            _execute_test_group("UI", [_test_case("TC-1"), _test_case("TC-2")], ["a-1"]), timeout=5
        )

    assert [(r.testCaseKey, r.testExecutionStatus) for r in results] == [("TC-1", "error"), ("TC-2", "error")]
    assert all("no execution agent remained available" in r.generalErrorMessage for r in results)


@pytest.mark.asyncio
async def test_agent_worker_records_and_reraises_cancellation(mock_registry, mock_queue):
    mock_queue.get.side_effect = [(_test_case(), "UI")]

    with (
        patch("orchestrator.main._execute_single_test", new_callable=AsyncMock, side_effect=asyncio.CancelledError),
        patch("orchestrator.main._record_error") as mock_record_error,
        pytest.raises(asyncio.CancelledError),
    ):
        await _agent_worker("agent-1", mock_queue, [], ["agent-1"])

    mock_record_error.assert_called_once()


@pytest.mark.asyncio
async def test_execute_single_test_keeps_the_status_of_an_http_exception(mock_registry):
    """The manual reservation's 409 must reach the caller instead of being turned into a 500."""
    with (
        patch(
            "orchestrator.main._send_task_to_agent",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=409, detail="Execution agent is busy."),
        ),
        pytest.raises(HTTPException) as raised,
    ):
        await _execute_single_test("agent-1", _test_case(), "manual", selected_agent_id="agent-1")

    assert raised.value.status_code == 409


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [(None, 404), (AgentStatus.BUSY, 409), (AgentStatus.BROKEN, 503)],
    ids=["unknown", "busy", "broken"],
)
@pytest.mark.asyncio
async def test_manual_reservation_rejects_an_unusable_agent(mock_registry, status, expected_code):
    mock_registry.get_card = AsyncMock(return_value=None if status is None else agent_card())
    mock_registry.get_status = AsyncMock(return_value=status)
    mock_registry.update_status = AsyncMock()

    with pytest.raises(HTTPException) as raised:
        await _send_task_to_agent_with_message(MagicMock(), "manual run", selected_agent_id="agent-1")

    assert raised.value.status_code == expected_code
    mock_registry.update_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_task_cancellation_releases_the_agent_for_recovery_and_reraises(mock_registry):
    mock_registry.update_status = AsyncMock()
    mock_registry.set_current_task = AsyncMock()

    with (
        patch(
            "orchestrator.main.reserve_agent_waiting_if_needed",
            new_callable=AsyncMock,
            return_value=("agent-1", agent_card()),
        ),
        patch("orchestrator.main.task_history") as mock_history,
        patch("orchestrator.main.create_client", new_callable=AsyncMock, side_effect=asyncio.CancelledError),
        patch("orchestrator.main._finalize_task", new_callable=AsyncMock) as mock_finalize,
        patch("orchestrator.main.cancellation_queue") as mock_cancellation_queue,
        patch("orchestrator.main._record_error") as mock_record_error,
        pytest.raises(asyncio.CancelledError),
    ):
        mock_history.add = AsyncMock()
        mock_cancellation_queue.put = AsyncMock()
        await _send_task_to_agent_with_message(MagicMock(), "some task")

    assert mock_finalize.await_args.args[2] == TaskStatus.CANCELLED
    mock_registry.update_status.assert_awaited_with("agent-1", AgentStatus.BROKEN, BrokenReason.TASK_STUCK, None)
    assert mock_cancellation_queue.put.await_args.args[0][0] == "agent-1"
    mock_record_error.assert_called_once()


@pytest.mark.asyncio
async def test_incident_fan_out_records_and_reraises_cancellation():
    failed = TestExecutionResult(
        stepResults=[],
        testCaseKey="TC-1",
        testCaseName="Name",
        testExecutionStatus="failed",
        generalErrorMessage="boom",
        start_timestamp="now",
        end_timestamp="then",
        system_description="Linux",
        test_case=_test_case(),
    )
    with (
        patch(
            "orchestrator.main._request_incident_creation", new_callable=AsyncMock, side_effect=asyncio.CancelledError
        ),
        patch("orchestrator.main._record_error") as mock_record_error,
        pytest.raises(asyncio.CancelledError),
    ):
        await _request_incident_creation_for_failed_tests([failed], "PROJ")

    mock_record_error.assert_called_once()


class TestGenerateTestReport:
    """WS15: the upload and the HTML report are independent, tolerated steps."""

    @pytest.fixture
    def reporting_client(self):
        with patch("orchestrator.main.get_test_reporting_client") as factory:
            yield factory.return_value

    @pytest.mark.asyncio
    async def test_a_clean_run_reports_no_failure(self, reporting_client):
        client = MagicMock()
        client.create_test_plan.return_value = "CYCLE-1"

        failures = await _generate_test_report(["result"], "PROJ", client)

        assert failures == []
        client.create_test_execution.assert_called_once_with(["result"], "PROJ", "CYCLE-1")
        reporting_client.generate_report.assert_called_once_with(["result"])

    @pytest.mark.asyncio
    async def test_a_failed_upload_still_generates_the_report(self, reporting_client):
        client = MagicMock()
        client.create_test_plan.side_effect = RuntimeError("TMS down")

        with patch("orchestrator.main._record_error") as mock_record_error:
            failures = await _generate_test_report(["result"], "PROJ", client)

        assert len(failures) == 1 and "TMS down" in failures[0]
        mock_record_error.assert_called_once_with(failures[0])
        reporting_client.generate_report.assert_called_once()

    @pytest.mark.asyncio
    async def test_a_missing_test_plan_skips_only_the_upload(self, reporting_client):
        client = MagicMock()
        client.create_test_plan.return_value = None

        with patch("orchestrator.main._record_error"):
            failures = await _generate_test_report(["result"], "PROJ", client)

        assert failures == ["No test plan was created; the upload of the test execution results was skipped."]
        client.create_test_execution.assert_not_called()
        reporting_client.generate_report.assert_called_once()

    @pytest.mark.asyncio
    async def test_a_failed_report_is_tolerated(self, reporting_client):
        client = MagicMock()
        client.create_test_plan.return_value = "CYCLE-1"
        reporting_client.generate_report.side_effect = RuntimeError("allure crashed")

        with patch("orchestrator.main._record_error"):
            failures = await _generate_test_report(["result"], "PROJ", client)

        assert len(failures) == 1 and "allure crashed" in failures[0]

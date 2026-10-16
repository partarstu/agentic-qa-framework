# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from a2a.helpers import new_text_message
from a2a.types import Artifact, Message, Part, Role, Task, TaskState, TaskStatus
from fastapi import HTTPException

from common.a2a_data import data_objects, data_part
from orchestrator.delegation import DELEGATION_CAPABILITY, DelegationExecutor, read_delegation_request
from orchestrator.main import orchestrator_app

_KEY = "internal-key"
_HEADERS = {"X-API-Key": _KEY, "A2A-Version": "1.0"}
_TEST_CASE = {"name": "Order a lamp", "steps": [{"action": "Open the catalog"}]}


@pytest.fixture
def internal_key(monkeypatch):
    monkeypatch.setattr("config.INTERNAL_SERVICE_API_KEY", _KEY)


@pytest.fixture
def mock_error_history():
    with patch("orchestrator.main.error_history") as history:
        history.add = AsyncMock()
        yield history


def _send_body(*parts: dict[str, Any]) -> dict[str, Any]:
    message = {"messageId": "message-1", "role": "ROLE_USER", "parts": list(parts)}
    return {"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {"message": message}}


def _delegation(**overrides: Any) -> dict[str, Any]:
    return {
        "data": {"capability": "Select recorded procedures", "payload": _TEST_CASE, "timeout_seconds": 900} | overrides
    }


async def _post(body: dict[str, Any], headers: dict[str, str] | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=orchestrator_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://orchestrator") as client:
        return await client.post("/a2a/", json=body, headers=_HEADERS if headers is None else headers)


def _task_of(response: httpx.Response) -> dict[str, Any]:
    return response.json()["result"]["task"]


def _remote_task(state: TaskState, *, artifacts: list[Artifact] | None = None, reason: str = "") -> Task:
    status = TaskStatus(state=state, message=new_text_message(reason)) if reason else TaskStatus(state=state)
    return Task(id="remote-task", status=status, artifacts=artifacts or [])


@pytest.mark.asyncio
async def test_agent_card_is_rejected_with_401_without_the_internal_key(internal_key):
    transport = httpx.ASGITransport(app=orchestrator_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://orchestrator") as client:
        response = await client.get("/a2a/.well-known/agent-card.json", headers={"X-API-Key": "wrong"})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delegation_fails_closed_with_503_when_no_internal_key_is_configured(monkeypatch):
    monkeypatch.setattr("config.INTERNAL_SERVICE_API_KEY", None)

    response = await _post(_send_body(_delegation()))

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_agent_card_describes_the_delegation_capability(internal_key):
    transport = httpx.ASGITransport(app=orchestrator_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://orchestrator") as client:
        response = await client.get("/a2a/.well-known/agent-card.json", headers=_HEADERS)

    assert response.status_code == 200
    assert response.json()["description"] == DELEGATION_CAPABILITY
    assert response.json()["supportedInterfaces"][0]["url"].endswith("/a2a/")


@pytest.mark.asyncio
async def test_delegation_returns_the_artifacts_of_the_selected_agent(internal_key):
    selection = Artifact(
        artifact_id="a1", name="procedure_selection", parts=[data_part({"items": [], "aggregations": []})]
    )
    send = AsyncMock(return_value=_remote_task(TaskState.TASK_STATE_COMPLETED, artifacts=[selection]))

    with patch("orchestrator.main._send_task_to_agent_with_message", send):
        response = await _post(_send_body(_delegation()))

    task = _task_of(response)
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert task["artifacts"][0]["name"] == "procedure_selection"
    assert task["artifacts"][0]["parts"] == [{"data": {"items": [], "aggregations": []}}]
    forwarded_message, description = send.await_args.args
    assert description == "Select recorded procedures"
    assert data_objects(forwarded_message.parts) == [_TEST_CASE]
    assert send.await_args.kwargs["timeout_seconds"] == 900


@pytest.mark.asyncio
async def test_delegation_caps_the_requested_timeout(internal_key):
    send = AsyncMock(return_value=_remote_task(TaskState.TASK_STATE_COMPLETED, artifacts=[Artifact(name="result")]))

    with (
        patch("orchestrator.main._send_task_to_agent_with_message", send),
        patch("config.OrchestratorConfig.DELEGATION_MAX_TIMEOUT_SECONDS", 60.0),
    ):
        await _post(_send_body(_delegation(timeout_seconds=900)))

    assert send.await_args.kwargs["timeout_seconds"] == 60.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raised", "reason"),
    [
        (HTTPException(status_code=404, detail="No registered agent can execute the task."), "No registered agent"),
        (HTTPException(status_code=408, detail="Task timed out while waiting for completion."), "timed out"),
    ],
    ids=["no-fitting-agent", "timeout"],
)
async def test_delegation_fails_the_task_with_the_reason_of_the_send_path(internal_key, raised, reason):
    with patch("orchestrator.main._send_task_to_agent_with_message", AsyncMock(side_effect=raised)):
        response = await _post(_send_body(_delegation()))

    task = _task_of(response)
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    assert reason in task["status"]["message"]["parts"][0]["text"]


@pytest.mark.asyncio
async def test_delegation_fails_and_records_the_error_when_the_agent_fails(internal_key, mock_error_history):
    failed = _remote_task(TaskState.TASK_STATE_FAILED, reason="Invalid request: The test case name is blank")

    with patch("orchestrator.main._send_task_to_agent_with_message", AsyncMock(return_value=failed)):
        response = await _post(_send_body(_delegation()))

    task = _task_of(response)
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    assert "The test case name is blank" in task["status"]["message"]["parts"][0]["text"]
    mock_error_history.add.assert_awaited_once()
    assert "The test case name is blank" in mock_error_history.add.await_args.args[0].message


@pytest.mark.asyncio
async def test_delegation_fails_and_records_the_error_when_sending_raises_unexpectedly(
    internal_key, mock_error_history
):
    with patch("orchestrator.main._send_task_to_agent_with_message", AsyncMock(side_effect=ConnectionError("refused"))):
        response = await _post(_send_body(_delegation()))

    assert _task_of(response)["status"]["state"] == "TASK_STATE_FAILED"
    mock_error_history.add.assert_awaited_once()
    assert "refused" in mock_error_history.add.await_args.args[0].message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parts",
    [
        [{"text": "Select procedures for this test case"}],
        [_delegation(), _delegation()],
        [_delegation(capability="")],
        [_delegation(timeout_seconds=0)],
        [_delegation(command="drop")],
        [_delegation(payload={"blob": "x" * 1_000_001})],
    ],
    ids=["no-data-part", "two-data-parts", "blank-capability", "zero-timeout", "unknown-field", "oversized-payload"],
)
async def test_invalid_delegation_request_fails_and_is_recorded_without_sending(
    internal_key, mock_error_history, parts
):
    send = AsyncMock()

    with patch("orchestrator.main._send_task_to_agent_with_message", send):
        response = await _post(_send_body(*parts))

    task = _task_of(response)
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    assert task["status"]["message"]["parts"][0]["text"].startswith("Invalid delegation request")
    send.assert_not_awaited()
    mock_error_history.add.assert_awaited_once()


def test_read_delegation_request_names_the_invalid_field_without_echoing_the_payload():
    message = Message(
        role=Role.ROLE_USER,
        message_id="m1",
        parts=[Part(text="ignored"), data_part(_delegation(timeout_seconds=-1)["data"])],
    )

    with pytest.raises(ValueError, match="timeout_seconds") as raised:
        read_delegation_request(message)

    assert "Order a lamp" not in str(raised.value)


def test_data_objects_skip_parts_without_a_json_object():
    list_part = Part()
    list_part.data.list_value.values.add().string_value = "x"

    assert data_objects([Part(text="t"), list_part, data_part({"a": "b"})]) == [{"a": "b"}]


def _context(message: Message) -> MagicMock:
    return MagicMock(task_id="task-1", context_id="context-1", message=message, current_task=None)


@pytest.mark.asyncio
async def test_cancel_stops_the_running_delegation_and_marks_the_task_cancelled():
    started = asyncio.Event()

    async def _never_finishing_delegate(*_: Any) -> list[Artifact]:
        started.set()
        await asyncio.Event().wait()
        return []

    executor = DelegationExecutor(_never_finishing_delegate, MagicMock())
    message = Message(role=Role.ROLE_USER, message_id="m1", parts=[data_part(_delegation()["data"])])
    event_queue = MagicMock(enqueue_event=AsyncMock())
    with patch("orchestrator.delegation.TaskUpdater") as updater_class:
        updater = updater_class.return_value
        updater.start_work, updater.cancel, updater.failed, updater.complete = (
            AsyncMock(),
            AsyncMock(),
            AsyncMock(),
            AsyncMock(),
        )
        execution = asyncio.create_task(executor.execute(_context(message), event_queue))
        await asyncio.wait_for(started.wait(), timeout=5)

        await executor.cancel(_context(message), event_queue)
        await asyncio.wait_for(execution, timeout=5)

    updater.cancel.assert_awaited_once()
    updater.complete.assert_not_awaited()
    updater.failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_without_a_running_delegation_marks_the_task_cancelled():
    executor = DelegationExecutor(AsyncMock(), MagicMock())

    with patch("orchestrator.delegation.TaskUpdater") as updater_class:
        updater_class.return_value.cancel = AsyncMock()
        await executor.cancel(_context(Message()), MagicMock())

    updater_class.return_value.cancel.assert_awaited_once()

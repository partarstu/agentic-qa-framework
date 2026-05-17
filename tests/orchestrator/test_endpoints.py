import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.types import Artifact, Part, Task, TaskState, TaskStatus
from fastapi.testclient import TestClient

import config
from common.streaming import SnapshotEvent
from orchestrator.auth import auth_service
from orchestrator.main import (
    _build_snapshot,
    _mint_stream_token,
    _sse_hub_events,
    _validate_api_key,
    _validate_stream_token,
    orchestrator_app,
)

client = TestClient(orchestrator_app)


# Override auth dependency
def mock_validate_api_key():
    pass


orchestrator_app.dependency_overrides[_validate_api_key] = mock_validate_api_key


@pytest.fixture
def mock_task_completed():
    task = MagicMock(spec=Task)
    task.status = TaskStatus(state=TaskState.TASK_STATE_COMPLETED)
    task.artifacts = [Artifact(name="art-1", parts=[Part(text='{"message": "success"}')])]
    return task


@pytest.mark.asyncio
async def test_review_jira_requirements_endpoint(mock_task_completed):
    with patch("orchestrator.main._send_task_to_agent", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_task_completed

        response = client.post("/new-requirements-available", json={"issue_key": "TEST-1"})

        assert response.status_code == 200
        assert "completed" in response.json()["message"]
        mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_review_jira_requirements_no_issue_key():
    response = client.post("/new-requirements-available", json={})
    assert response.status_code == 400
    assert "no Jira issue key" in response.json()["detail"]


@pytest.mark.asyncio
async def test_trigger_test_case_generation_workflow(mock_task_completed):
    # This endpoint calls multiple agents in sequence.
    # _request_test_cases_generation -> returns GeneratedTestCases
    # _request_test_cases_classification
    # _request_test_cases_review

    with (
        patch("orchestrator.main._request_test_cases_generation", new_callable=AsyncMock) as mock_gen,
        patch("orchestrator.main._request_test_cases_classification", new_callable=AsyncMock) as mock_class,
        patch("orchestrator.main._request_test_cases_review", new_callable=AsyncMock) as mock_review,
    ):
        mock_gen_obj = MagicMock()
        mock_gen_obj.test_cases = [MagicMock()]
        mock_gen.return_value = mock_gen_obj

        response = client.post("/story-ready-for-test-case-generation", json={"issue_key": "TEST-1"})

        assert response.status_code == 200
        mock_gen.assert_called_once()
        mock_class.assert_called_once()
        mock_review.assert_called_once()


@pytest.mark.asyncio
async def test_execute_tests_endpoint():
    # This is complex. It fetches TCs, groups them, executes them, generates report.
    # We'll mock the high level functions.

    with (
        patch("orchestrator.main.get_test_management_client") as mock_get_client,
        patch("orchestrator.main._group_test_cases_by_labels", new_callable=AsyncMock) as mock_group,
        patch("orchestrator.main._request_all_test_cases_execution", new_callable=AsyncMock) as mock_exec,
        patch("orchestrator.main._generate_test_report", new_callable=AsyncMock) as mock_report,
    ):
        mock_tm_client = MagicMock()
        mock_get_client.return_value = mock_tm_client
        mock_tm_client.fetch_ready_for_execution_test_cases_by_labels.return_value = {
            config.OrchestratorConfig.AUTOMATED_TC_LABEL: [MagicMock()]
        }

        mock_group.return_value = {"UI": [MagicMock()]}
        mock_exec.return_value = [MagicMock()]  # results

        response = client.post("/execute-tests", json={"project_key": "PROJ"})

        assert response.status_code == 200
        mock_exec.assert_called_once()
        mock_report.assert_called_once()


# =============================================================================
# POST /api/dashboard/stream-token
# =============================================================================


def _valid_bearer_header() -> dict:
    token = auth_service.create_token("test-user").access_token
    return {"Authorization": f"Bearer {token}"}


def test_stream_token_without_jwt_returns_401():
    response = client.post("/api/dashboard/stream-token")
    assert response.status_code == 401


def test_stream_token_with_valid_jwt_returns_token_and_expiry():
    response = client.post("/api/dashboard/stream-token", headers=_valid_bearer_header())
    assert response.status_code == 200
    body = response.json()
    assert "stream_token" in body
    assert "expires_at" in body
    assert len(body["stream_token"]) > 10


# =============================================================================
# GET /api/dashboard/stream — auth guard
# =============================================================================


def test_global_sse_stream_without_token_returns_422():
    # stream_token query param is required; missing → 422 Unprocessable Entity
    response = client.get("/api/dashboard/stream")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_global_sse_stream_with_invalid_token_returns_401():
    response = client.get("/api/dashboard/stream", params={"stream_token": "bogus-token"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_global_sse_stream_with_expired_token_returns_401():
    token, _ = await _mint_stream_token("test-user")
    # Forcibly expire the token by backdating it in the store
    from orchestrator.main import _stream_token_store
    _stream_token_store[token] = ("test-user", datetime.now(UTC) - timedelta(seconds=1))

    response = client.get("/api/dashboard/stream", params={"stream_token": token})
    assert response.status_code == 401


# =============================================================================
# _build_snapshot — schema check
# =============================================================================


@pytest.mark.asyncio
async def test_build_snapshot_returns_valid_snapshot_event():
    with (
        patch("orchestrator.main.agent_registry") as mock_registry,
        patch("orchestrator.main.task_history") as mock_history,
    ):
        mock_registry.get_all_cards = AsyncMock(return_value={})
        mock_history.get_all = AsyncMock(return_value=[])

        snapshot = await _build_snapshot()

    assert isinstance(snapshot, SnapshotEvent)
    assert snapshot.version == 1
    assert isinstance(snapshot.agents, list)
    assert isinstance(snapshot.running_tasks, list)


# =============================================================================
# _sse_hub_events — live event forwarding and auth-error frame
# =============================================================================


@pytest.mark.asyncio
async def test_sse_hub_events_forwards_live_event():
    live = {"type": "agent_activity", "task_id": "t1", "agent_id": "a1", "text": "working", "version": 1}

    async def one_event_gen():
        yield live
        await asyncio.sleep(100)  # block after first event

    expires = datetime.now(UTC) + timedelta(minutes=5)
    events = []

    async for sse in _sse_hub_events(one_event_gen(), expires):
        events.append(sse)
        break  # close generator after first frame

    assert len(events) == 1
    assert events[0].event == "agent_activity"
    data = json.loads(events[0].data)
    assert data["task_id"] == "t1"
    assert data["text"] == "working"


@pytest.mark.asyncio
async def test_sse_hub_events_emits_auth_error_when_token_expired_on_heartbeat():
    async def empty_gen():
        return
        yield {}  # makes it an async generator

    expired = datetime.now(UTC) - timedelta(seconds=1)
    events = []

    async def instant_timeout(coro, timeout):
        try:
            coro.close()
        except Exception:
            pass
        raise asyncio.TimeoutError()

    with patch("orchestrator.main.asyncio.wait_for", instant_timeout):
        async for sse in _sse_hub_events(empty_gen(), expired):
            events.append(sse)

    assert len(events) == 1
    assert events[0].event == "auth-error"

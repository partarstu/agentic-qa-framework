# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the RAG sync endpoints and trigger modes.

Every external boundary (Qdrant locks, the Cloud Run Admin API, the local sync service)
is mocked. The lock state machine itself is covered in tests/services/test_rag_sync_runtime.py.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import orchestrator.main as main
from common.models import ConfluenceSyncRequest, JiraSyncRequest
from common.services.sync_lock_store import SyncLockHeldError
from orchestrator.main import _validate_api_key, orchestrator_app
from orchestrator.rag_sync_trigger import SyncStartResult, SyncTriggerError


@pytest.fixture
def client():
    orchestrator_app.dependency_overrides[_validate_api_key] = lambda: None
    with TestClient(orchestrator_app) as test_client:
        yield test_client
    orchestrator_app.dependency_overrides.pop(_validate_api_key, None)


def _validation_messages(response) -> str:
    """The messages of a FastAPI 422 body, joined so a test can assert one substring."""
    return " ".join(error["msg"] for error in response.json()["detail"])


@pytest.fixture
def reset_trigger_singleton():
    yield
    main._rag_sync_trigger = None
    main._rag_sync_lock = asyncio.Lock()


def _mock_trigger(monkeypatch, acquire_result="lock-token", acquire_error=None, start_result=None, start_error=None):
    """Patch the trigger singleton with a controllable fake.

    The orchestrator acquires the scope lock under its in-process mutex and starts
    the sync outside it, so the fake exposes the two split methods.
    """
    trigger = MagicMock()
    trigger.acquire = AsyncMock(return_value=acquire_result, side_effect=acquire_error)
    trigger.start = AsyncMock(return_value=start_result, side_effect=start_error)
    main._rag_sync_trigger = trigger
    return trigger


class TestUpdateJiraDb:
    def test_local_mode_returns_run_result(self, client, monkeypatch, reset_trigger_singleton):
        monkeypatch.setattr(main.config.RagSyncConfig, "JOB_NAME", None)
        monkeypatch.setattr(main.config.RagSyncConfig, "SERVICE_URL", "http://local-sync:8080")
        _mock_trigger(
            monkeypatch,
            start_result=SyncStartResult(
                status_code=200,
                response={
                    "message": "Jira sync completed.",
                    "details": {"status": "completed", "processed_count": 2},
                },
            ),
        )

        response = client.post("/update-jira-db", json={"project_key": "PROJ"})

        assert response.status_code == 200
        assert response.json()["details"]["processed_count"] == 2
        trigger = main._rag_sync_trigger
        trigger.acquire.assert_awaited_once_with("jira", "PROJ")
        trigger.start.assert_awaited_once_with("jira", "PROJ", JiraSyncRequest(project_key="PROJ"), "lock-token")

    def test_local_mode_rejection_reaches_the_caller_with_its_status(
        self, client, monkeypatch, reset_trigger_singleton
    ):
        """A local sync service answering 401/409/422 must not be reported as a completed sync."""
        monkeypatch.setattr(main.config.RagSyncConfig, "JOB_NAME", None)
        monkeypatch.setattr(main.config.RagSyncConfig, "SERVICE_URL", "http://local-sync:8080")
        _mock_trigger(monkeypatch, start_result=SyncStartResult(status_code=401, response={"detail": "Unauthorized"}))

        response = client.post("/update-jira-db", json={"project_key": "PROJ"})

        assert response.status_code == 401
        assert response.json()["detail"] == {"detail": "Unauthorized"}

    def test_job_mode_returns_202_with_execution(self, client, monkeypatch, reset_trigger_singleton):
        monkeypatch.setattr(main.config.RagSyncConfig, "JOB_NAME", "projects/p/locations/us-central1/jobs/rag-sync")
        _mock_trigger(
            monkeypatch,
            start_result=SyncStartResult(
                status_code=202, execution="projects/p/locations/us-central1/executions/abc123"
            ),
        )

        response = client.post("/update-jira-db", json={"project_key": "PROJ"})

        assert response.status_code == 202
        assert response.json()["execution"].endswith("abc123")

    def test_invalid_project_key_rejected(self, client):
        response = client.post("/update-jira-db", json={"project_key": "invalid key!"})
        assert response.status_code == 422

    def test_live_lock_conflicts_with_409(self, client, reset_trigger_singleton):
        _mock_trigger(
            None,
            acquire_error=SyncLockHeldError(
                "A sync is already running for scope jira:PROJ (started at 1, lock expires at 2)."
            ),
        )

        response = client.post("/update-jira-db", json={"project_key": "PROJ"})

        assert response.status_code == 409
        assert "already running" in response.json()["detail"]

    def test_no_runtime_configured_returns_503(self, client, monkeypatch, reset_trigger_singleton):
        monkeypatch.setattr(main.config.RagSyncConfig, "JOB_NAME", None)
        monkeypatch.setattr(main.config.RagSyncConfig, "SERVICE_URL", None)
        _mock_trigger(
            None,
            acquire_error=SyncTriggerError(
                "No RAG sync runtime is configured: set RAG_SYNC_JOB_NAME (job mode) or "
                "RAG_SYNC_SERVICE_URL (local mode).",
                start_confirmed=True,
            ),
        )

        response = client.post("/update-jira-db", json={"project_key": "PROJ"})

        assert response.status_code == 503
        assert "RAG_SYNC_JOB_NAME" in response.json()["detail"]

    def test_unconfirmed_start_keeps_lock_with_502(self, client, reset_trigger_singleton):
        _mock_trigger(
            None,
            start_error=SyncTriggerError("Failed to start the RAG sync: timeout.", start_confirmed=False),
        )

        response = client.post("/update-jira-db", json={"project_key": "PROJ"})

        assert response.status_code == 502
        assert "unconfirmed" in response.json()["detail"]


class TestUpdateConfluenceDb:
    def test_scope_options_forwarded_as_runner_args(self, client, monkeypatch, reset_trigger_singleton):
        monkeypatch.setattr(main.config.RagSyncConfig, "JOB_NAME", "projects/p/locations/us-central1/jobs/rag-sync")
        _mock_trigger(monkeypatch, start_result=SyncStartResult(status_code=202, execution="exec-1"))

        scope = {
            "space_key": "~dev",
            "page_id": 12345,
            "attachment_name_pattern": "^report.*\\.pdf$",
            "skip_page_body": True,
        }
        response = client.post("/update-confluence-db", json=scope)

        assert response.status_code == 202
        main._rag_sync_trigger.start.assert_awaited_once_with(
            "confluence", "~dev", ConfluenceSyncRequest(**scope), "lock-token"
        )
        assert ConfluenceSyncRequest(**scope).to_cli_args() == [
            "--space-key",
            "~dev",
            "--page-id",
            "12345",
            "--attachment-name-pattern",
            "^report.*\\.pdf$",
            "--skip-page-body",
        ]

    def test_personal_space_key_accepted(self, client, reset_trigger_singleton):
        _mock_trigger(None, start_result=SyncStartResult(status_code=202, execution="exec-1"))
        response = client.post("/update-confluence-db", json={"space_key": "~john.doe"})
        assert response.status_code == 202

    def test_invalid_pattern_returns_422(self, client):
        response = client.post(
            "/update-confluence-db", json={"space_key": "DEV", "attachment_name_pattern": "([unclosed"}
        )
        assert response.status_code == 422
        assert "Invalid name pattern" in _validation_messages(response)

    def test_invalid_page_id_rejected(self, client):
        response = client.post("/update-confluence-db", json={"space_key": "DEV", "page_id": -5})
        assert response.status_code == 422

    def test_exponentially_backtracking_pattern_returns_422(self, client):
        response = client.post("/update-confluence-db", json={"space_key": "DEV", "attachment_name_pattern": "(a+)+b"})
        assert response.status_code == 422
        assert "nested repetition" in _validation_messages(response)

    @pytest.mark.parametrize(
        "drive_id",
        ["../sites/root/drive", "b!abc/items", "b!abc?select=id"],
        ids=["traversal", "extra_path_segment", "query_string"],
    )
    def test_drive_id_carrying_path_or_query_characters_is_rejected(self, client, drive_id):
        """drive_id is interpolated into the Graph REST path, so it may not carry path or query syntax."""
        response = client.post("/update-sharepoint-db", json={"drive_id": drive_id})
        assert response.status_code == 422


async def _acquire_and_start(trigger_obj, source, scope_id, request):
    """The sequence the endpoints run: acquire the scope lock, then start under its token."""
    token = await trigger_obj.acquire(source, scope_id)
    return await trigger_obj.start(source, scope_id, request, token)


class TestTriggerModes:
    """The trigger's own mode selection, with the lock store mocked."""

    @pytest.fixture
    def trigger(self, monkeypatch):
        from orchestrator.rag_sync_trigger import RagSyncTrigger

        metadata_db = MagicMock()
        metadata_db.get_payload_record = AsyncMock(return_value=None)
        metadata_db.upsert_payload_record = AsyncMock()
        with patch("orchestrator.rag_sync_trigger.SyncLockStore") as lock_cls:
            lock_store = MagicMock()
            lock_store.acquire = AsyncMock()
            lock_cls.return_value = lock_store
            trigger = RagSyncTrigger(metadata_db)
            yield trigger, lock_store

    async def test_local_mode_forwards_to_service_with_lock_token(self, trigger, monkeypatch):
        trigger_obj, lock_store = trigger
        state = MagicMock()
        state.acquired = True
        state.lock_info = {"holder_token": "tok"}
        lock_store.acquire.return_value = state
        monkeypatch.setattr(
            trigger_obj._config.JOB_NAME if hasattr(trigger_obj, "_config") else main.config.RagSyncConfig,
            "JOB_NAME",
            None,
        )
        monkeypatch.setattr(main.config.RagSyncConfig, "SERVICE_URL", "http://local-sync:8080")

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"message": "done"}

        with patch("orchestrator.rag_sync_trigger.httpx.AsyncClient") as client_cls:
            http = AsyncMock()
            http.post = AsyncMock(return_value=response)
            client_cls.return_value.__aenter__ = AsyncMock(return_value=http)
            client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _acquire_and_start(trigger_obj, "jira", "PROJ", JiraSyncRequest(project_key="PROJ"))

        assert result.status_code == 200
        http.post.assert_awaited_once_with(
            "http://local-sync:8080/sync/jira", json={"project_key": "PROJ", "lock_token": "tok"}, headers={}
        )

    @pytest.mark.parametrize(
        ("status_code", "released"),
        [(401, True), (422, True), (409, False)],
        ids=["unauthorized_releases", "unprocessable_releases", "conflict_keeps_the_other_holders_lock"],
    )
    async def test_local_mode_rejection_frees_the_scope(self, trigger, monkeypatch, status_code, released):
        """A runner that rejects the request started nothing, so the scope must not stay locked for the TTL."""
        trigger_obj, lock_store = trigger
        state = MagicMock()
        state.acquired = True
        state.lock_info = {"holder_token": "tok"}
        lock_store.acquire.return_value = state
        lock_store.read = AsyncMock(return_value={"holder_token": "tok"})
        lock_store.release = AsyncMock(return_value=True)
        monkeypatch.setattr(main.config.RagSyncConfig, "JOB_NAME", None)
        monkeypatch.setattr(main.config.RagSyncConfig, "SERVICE_URL", "http://local-sync:8080")

        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = {"detail": "rejected"}

        with patch("orchestrator.rag_sync_trigger.httpx.AsyncClient") as client_cls:
            http = AsyncMock()
            http.post = AsyncMock(return_value=response)
            client_cls.return_value.__aenter__ = AsyncMock(return_value=http)
            client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _acquire_and_start(trigger_obj, "jira", "PROJ", JiraSyncRequest(project_key="PROJ"))

        assert result.status_code == status_code
        assert lock_store.release.await_count == (1 if released else 0)

    async def test_neither_mode_configured_raises(self, trigger, monkeypatch):
        trigger_obj, _ = trigger
        monkeypatch.setattr(main.config.RagSyncConfig, "JOB_NAME", None)
        monkeypatch.setattr(main.config.RagSyncConfig, "SERVICE_URL", None)

        with pytest.raises(SyncTriggerError, match="No RAG sync runtime is configured"):
            await _acquire_and_start(trigger_obj, "jira", "PROJ", JiraSyncRequest(project_key="PROJ"))

    async def test_live_lock_raises_with_lock_info(self, trigger):
        trigger_obj, lock_store = trigger
        # A mode must be configured before the lock is even attempted.
        main.config.RagSyncConfig.JOB_NAME = "projects/p/locations/us-central1/jobs/rag-sync"
        state = MagicMock()
        state.acquired = False
        state.lock_info = {"acquired_at": 100.0, "expires_at": 200.0}
        lock_store.acquire.return_value = state

        with pytest.raises(SyncLockHeldError, match="already running"):
            await _acquire_and_start(trigger_obj, "jira", "PROJ", JiraSyncRequest(project_key="PROJ"))
        main.config.RagSyncConfig.JOB_NAME = None

    async def test_definite_job_failure_releases_the_lock(self, trigger):
        from google.api_core.exceptions import PermissionDenied

        trigger_obj, lock_store = trigger
        main.config.RagSyncConfig.JOB_NAME = "projects/p/locations/us-central1/jobs/rag-sync"
        main.config.RagSyncConfig.SERVICE_URL = None
        state = MagicMock()
        state.acquired = True
        state.lock_info = {"holder_token": "tok"}
        lock_store.acquire.return_value = state
        lock_store.read = AsyncMock(return_value={"holder_token": "tok"})
        lock_store.release = AsyncMock(return_value=True)

        with (
            patch(
                "orchestrator.rag_sync_trigger.RagSyncTrigger._start_job",
                side_effect=PermissionDenied("denied"),
            ),
            pytest.raises(SyncTriggerError) as exc_info,
        ):
            await _acquire_and_start(trigger_obj, "jira", "PROJ", JiraSyncRequest(project_key="PROJ"))

        assert exc_info.value.start_confirmed is True
        lock_store.read.assert_awaited_with("jira:PROJ")
        lock_store.release.assert_called_once()
        main.config.RagSyncConfig.JOB_NAME = None

    async def test_unconfirmed_job_failure_keeps_the_lock(self, trigger):
        trigger_obj, lock_store = trigger
        main.config.RagSyncConfig.JOB_NAME = "projects/p/locations/us-central1/jobs/rag-sync"
        main.config.RagSyncConfig.SERVICE_URL = None
        state = MagicMock()
        state.acquired = True
        state.lock_info = {"holder_token": "tok"}
        lock_store.acquire.return_value = state

        with (
            patch(
                "orchestrator.rag_sync_trigger.RagSyncTrigger._start_job",
                side_effect=TimeoutError("the Admin API call timed out"),
            ),
            pytest.raises(SyncTriggerError) as exc_info,
        ):
            await _acquire_and_start(trigger_obj, "jira", "PROJ", JiraSyncRequest(project_key="PROJ"))

        assert exc_info.value.start_confirmed is False
        lock_store.release.assert_not_called()
        main.config.RagSyncConfig.JOB_NAME = None

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the local RAG sync service endpoints."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

SERVICES_DIR = Path(__file__).resolve().parents[2] / "services"
if str(SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICES_DIR))

from rag_sync import local_service  # noqa: E402

from common.models import RagUpdateResult  # noqa: E402

API_KEY = "internal-key"


@pytest.fixture(autouse=True)
def report_outcome():
    """Keeps every sync off the metadata store, whose connection retries would stall each test for seconds."""
    with patch("rag_sync.outcome_reporting.report_terminal_outcome", new_callable=AsyncMock) as report:
        yield report


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(local_service.config, "INTERNAL_SERVICE_API_KEY", API_KEY)
    return TestClient(local_service.app)


class TestLockTokenForwarding:
    def test_jira_sync_runs_under_the_orchestrator_lock_token(self, client):
        sync_project = AsyncMock(return_value=RagUpdateResult(status="completed", processed_count=1))
        with patch("rag_sync.jira_sync.JiraRagSyncRunner") as runner_cls:
            runner_cls.return_value.sync_project = sync_project
            response = client.post(
                "/sync/jira", json={"project_key": "PROJ", "lock_token": "tok"}, headers={"X-API-Key": API_KEY}
            )

        assert response.status_code == 200
        sync_project.assert_awaited_once_with("PROJ", lock_token="tok")

    def test_confluence_sync_runs_under_the_orchestrator_lock_token(self, client):
        sync_space = AsyncMock(return_value=RagUpdateResult(status="completed", processed_count=1))
        with patch("rag_sync.confluence_sync.ConfluenceRagSyncRunner") as runner_cls:
            runner_cls.return_value.sync_space = sync_space
            response = client.post(
                "/sync/confluence", json={"space_key": "DEV", "lock_token": "tok"}, headers={"X-API-Key": API_KEY}
            )

        assert response.status_code == 200
        assert sync_space.await_args.kwargs["lock_token"] == "tok"


class TestFailedRun:
    @pytest.mark.parametrize(
        ("path", "body", "runner_patch", "method"),
        [
            ("/sync/jira", {"project_key": "PROJ"}, "rag_sync.jira_sync.JiraRagSyncRunner", "sync_project"),
            (
                "/sync/confluence",
                {"space_key": "DEV"},
                "rag_sync.confluence_sync.ConfluenceRagSyncRunner",
                "sync_space",
            ),
        ],
        ids=["jira", "confluence"],
    )
    def test_a_failed_run_answers_with_its_reason_and_reports_the_outcome(
        self, client, report_outcome, path, body, runner_patch, method
    ):
        failure = RuntimeError("No Confluence space found for key 'DEV'.")
        with patch(runner_patch) as runner_cls:
            setattr(runner_cls.return_value, method, AsyncMock(side_effect=failure))
            response = client.post(path, json=body, headers={"X-API-Key": API_KEY})

        assert response.status_code == 500
        assert response.json()["detail"] == "RuntimeError: No Confluence space found for key 'DEV'."
        assert report_outcome.await_args.kwargs["error"] is failure

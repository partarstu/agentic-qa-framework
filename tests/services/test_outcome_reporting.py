# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the reporting-only terminal outcome of a RAG sync run (WS20)."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# The Docker image copies services/rag_sync/ to /app/rag_sync (flat layout); mirror it
# for the tests by putting services/ on the path (rag_sync is a namespace package).
SERVICES_DIR = Path(__file__).resolve().parents[2] / "services"
if str(SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICES_DIR))

from rag_sync.outcome_reporting import report_terminal_outcome  # noqa: E402

from common.models import RagUpdateResult  # noqa: E402


@pytest.fixture
def outcome_store():
    with (
        patch("rag_sync.outcome_reporting.VectorDbService") as service_class,
        patch("rag_sync.outcome_reporting.SyncOutcomeStore") as store_class,
    ):
        service_class.return_value.close = AsyncMock()
        store_class.return_value.write = AsyncMock()
        yield store_class.return_value


@pytest.fixture
def callback_client():
    with patch("rag_sync.outcome_reporting.httpx.AsyncClient") as client_class:
        client = client_class.return_value.__aenter__.return_value
        client.post = AsyncMock(return_value=MagicMock())
        yield client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "error", "expected_status"),
    [
        (RagUpdateResult(status="completed", processed_count=3), None, "completed"),
        (RagUpdateResult(status="completed_with_errors", processed_count=1), None, "completed_with_errors"),
        (None, RuntimeError("listing failed"), "failed"),
    ],
    ids=["clean", "partial", "failed"],
)
async def test_the_outcome_status_follows_the_run(outcome_store, result, error, expected_status):
    with patch("config.RagSyncConfig.CALLBACK_URL", None):
        await report_terminal_outcome("confluence", "DEV", result=result, error=error)

    scope, status, *_ = outcome_store.write.await_args.args
    assert (scope, status) == ("confluence:DEV", expected_status)


@pytest.mark.asyncio
async def test_the_callback_posts_the_outcome_with_the_api_key(outcome_store, callback_client):
    with (
        patch("config.RagSyncConfig.CALLBACK_URL", "http://orchestrator/sync-outcome"),
        patch("config.OrchestratorConfig.API_KEY", "key-1"),
    ):
        await report_terminal_outcome("jira", "PROJ", result=RagUpdateResult(status="completed", processed_count=2))

    url = callback_client.post.await_args.args[0]
    kwargs = callback_client.post.await_args.kwargs
    assert url == "http://orchestrator/sync-outcome"
    assert kwargs["headers"] == {"X-API-Key": "key-1"}
    assert (kwargs["json"]["scope"], kwargs["json"]["processed_count"]) == ("jira:PROJ", 2)


@pytest.mark.asyncio
async def test_no_callback_is_sent_without_a_configured_url(outcome_store, callback_client):
    with patch("config.RagSyncConfig.CALLBACK_URL", None):
        await report_terminal_outcome("jira", "PROJ", result=RagUpdateResult(status="completed", processed_count=0))

    callback_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_reporting_failures_never_escape(callback_client):
    """The real store swallows its own storage failures, so reporting cannot fail a sync."""
    callback_client.post.side_effect = RuntimeError("orchestrator down")

    with (
        patch("rag_sync.outcome_reporting.VectorDbService") as service_class,
        patch("config.RagSyncConfig.CALLBACK_URL", "http://orchestrator/sync-outcome"),
    ):
        service = service_class.return_value
        service.close = AsyncMock()
        service.get_payload_record = AsyncMock(side_effect=RuntimeError("qdrant down"))
        service.upsert_payload_record = AsyncMock(side_effect=RuntimeError("qdrant down"))

        await report_terminal_outcome("jira", "PROJ", error=RuntimeError("sync failed"))

    service.close.assert_awaited_once()

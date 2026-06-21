# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from common.models import JiraIssue
from common.services.rag_sync_service import JiraRagSyncService, _to_jql_timestamp


def _make_issue(
    issue_id: int,
    key: str,
    status: str = "Done",
    summary: str = "Summary",
    description: str = "Description",
    issue_type: str = "Bug",
    updated: str = "2025-01-15T10:30:00.000+0000",
) -> SimpleNamespace:
    """Build a minimal stand-in for a jira.resources.Issue."""
    return SimpleNamespace(
        id=str(issue_id),
        key=key,
        fields=SimpleNamespace(
            summary=summary,
            description=description,
            issuetype=SimpleNamespace(name=issue_type),
            status=SimpleNamespace(name=status),
            updated=updated,
        ),
    )


def _make_db_mock() -> MagicMock:
    db = MagicMock()
    db.delete = AsyncMock()
    db.upsert = AsyncMock()
    db.ensure_collection = AsyncMock()
    db.retrieve = AsyncMock(return_value=[])
    db.scroll_all_ids_by_project = AsyncMock(return_value=[])
    return db


@pytest.fixture
def service():
    issues_db = _make_db_mock()
    metadata_db = _make_db_mock()
    # __init__ creates the issues collection first, then the metadata collection.
    with patch("common.services.rag_sync_service.VectorDbService", side_effect=[issues_db, metadata_db]):
        svc = JiraRagSyncService()
    svc._valid_statuses = {"To Do", "In Progress", "Done"}
    return svc


def test_to_jql_timestamp_converts_iso_to_jql_format():
    assert _to_jql_timestamp("2025-01-15T10:30:00Z") == "2025-01-15 10:30"
    assert _to_jql_timestamp("1970-01-01T00:00:00Z") == "1970-01-01 00:00"


@pytest.mark.asyncio
async def test_sync_project_reconciles_upserts_and_deletes(service):
    # 9999 is stored locally but no longer exists in Jira -> stale.
    service._issues_db.scroll_all_ids_by_project = AsyncMock(return_value=[1001, 9999])

    fake_jira = MagicMock()
    fake_jira.search_issues.side_effect = [
        # 1. reconciliation: all current issue IDs in Jira
        [_make_issue(1001, "TEST-1"), _make_issue(1002, "TEST-2")],
        # 2. issues updated since the watermark: one active, one inactive
        [_make_issue(1002, "TEST-2", status="Done"), _make_issue(1003, "TEST-3", status="Closed")],
    ]

    with patch.object(JiraRagSyncService, "_create_jira_client", return_value=fake_jira):
        result = await service.sync_project("TEST")

    assert result.status == "completed"
    assert result.processed_count == 2

    # Stale issue removed during reconciliation, inactive issue removed during sync.
    service._issues_db.delete.assert_any_await([9999])
    service._issues_db.delete.assert_any_await([1003])

    # The single active issue was upserted.
    service._issues_db.upsert.assert_awaited_once()
    upserted = service._issues_db.upsert.await_args.kwargs["data"]
    assert isinstance(upserted, JiraIssue)
    assert upserted.id == 1002
    assert upserted.status == "Done"

    # Watermark timestamp persisted exactly once.
    service._metadata_db.upsert.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_project_no_updates_skips_writes(service):
    service._issues_db.scroll_all_ids_by_project = AsyncMock(return_value=[1001])

    fake_jira = MagicMock()
    fake_jira.search_issues.side_effect = [
        [_make_issue(1001, "TEST-1")],  # reconciliation: nothing stale
        [],  # no updated issues
    ]

    with patch.object(JiraRagSyncService, "_create_jira_client", return_value=fake_jira):
        result = await service.sync_project("TEST")

    assert result.processed_count == 0
    service._issues_db.delete.assert_not_awaited()
    service._issues_db.upsert.assert_not_awaited()
    service._metadata_db.upsert.assert_awaited_once()

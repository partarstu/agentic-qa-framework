# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the test-case RAG sync runner (WS17): full resync, the status filter,
the indexed_at deletion guard and the fail-fast listing contract.

Every external boundary (Qdrant, the test-management system) is mocked.
"""

import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qdrant_client import models

# The Docker image copies services/rag_sync/ to /app/rag_sync (flat layout); mirror it
# for the tests by putting services/ on the path (rag_sync is a namespace package).
SERVICES_DIR = Path(__file__).resolve().parents[2] / "services"
if str(SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICES_DIR))

from rag_sync.test_case_sync import TestCaseRagSyncRunner, _eligible_for_indexing  # noqa: E402

import config  # noqa: E402
from common.models import ListedTestCase, TestCase, TestStep  # noqa: E402
from common.services.sync_lock_store import LockState, scope_key  # noqa: E402

PROJECT_KEY = "SMOKE"


def _listed(key: str, status: str = "Draft") -> ListedTestCase:
    test_case = TestCase(
        key=key,
        name=f"Test case {key}",
        summary=f"Verify {key}",
        comment="",
        preconditions=None,
        steps=[TestStep(action="Do it", expected_results="It worked", test_data=["input"])],
        labels=["automated"],
        parent_issue_key=None,
    )
    return ListedTestCase(test_case=test_case, status=status)


def _point_id(key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"quaia:test-case:{config.TEST_MANAGEMENT_SYSTEM}:{key}"))


@pytest.fixture
def runner():
    with patch("common.services.vector_db_service.AsyncQdrantClient"):
        db = MagicMock()
        db.close = AsyncMock()
        db.scroll = AsyncMock(return_value=([], None))
        db.upsert_batch = AsyncMock()
        db.delete = AsyncMock()
        db.ensure_collection = AsyncMock()
        db.client = AsyncMock()
        db.client.scroll.return_value = ([], None)
        metadata_db = MagicMock()
        metadata_db.close = AsyncMock()
        lock_store = MagicMock()
        lock_store.acquire = AsyncMock(return_value=LockState(acquired=True, lock_info={"holder_token": "t"}))
        lock_store.mark_started = AsyncMock(return_value=True)
        lock_store.is_holder = AsyncMock(return_value=True)
        lock_store.release = AsyncMock(return_value=True)
        with (
            patch("rag_sync.test_case_sync.VectorDbService", side_effect=[metadata_db, db]),
            patch("common.services.sync_lock_store.SyncLockStore", return_value=lock_store),
            patch("rag_sync.test_case_sync.get_test_management_client") as mock_tms,
        ):
            runner = TestCaseRagSyncRunner()
            runner._db = db
            runner._lock_store = lock_store
            runner._tms = mock_tms
            yield runner


def _scroll_result(points: list[tuple[str, str, str]]):
    """Builds a scroll return value: (point id, content_hash, indexed_at) triples."""

    class Point:
        def __init__(self, point_id, payload):
            self.id = point_id
            self.payload = payload

    return (
        [
            Point(point_id, {"content_hash": content_hash, "indexed_at": indexed_at})
            for point_id, content_hash, indexed_at in points
        ],
        None,
    )


class TestFullResync:
    @pytest.mark.asyncio
    async def test_every_listed_test_case_is_upserted_on_an_empty_index(self, runner):
        runner._tms.return_value.fetch_test_cases_by_project.return_value = [
            _listed("SMOKE-1"),
            _listed("SMOKE-2", status="Approved"),
        ]
        runner._db.client.scroll.return_value = _scroll_result([])

        result = await runner.sync_project(PROJECT_KEY)

        assert result.status == "completed"
        assert result.processed_count == 2
        runner._db.ensure_collection.assert_awaited_once()
        upserted = [record for batch in runner._db.upsert_batch.await_args_list for record in batch.args[0]]
        assert {record.test_case_key for record in upserted} == {"SMOKE-1", "SMOKE-2"}

    @pytest.mark.asyncio
    async def test_the_collection_exists_before_the_stored_points_are_read(self, runner):
        """On the very first run the collection doesn't exist yet, and scrolling it would fail with a 404."""
        calls: list[str] = []
        runner._db.ensure_collection.side_effect = lambda: calls.append("ensure")

        async def _scroll(**kwargs):
            calls.append("scroll")
            return _scroll_result([])

        runner._db.client.scroll.side_effect = _scroll
        runner._tms.return_value.fetch_test_cases_by_project.return_value = [_listed("SMOKE-1")]

        await runner.sync_project(PROJECT_KEY)

        assert calls[:2] == ["ensure", "scroll"]

    @pytest.mark.asyncio
    async def test_unchanged_content_hash_skips_the_re_embedding(self, runner):
        from common.services.test_case_index import render_test_case

        listed = [_listed("SMOKE-1")]
        stored_record = render_test_case(PROJECT_KEY, listed[0])
        runner._tms.return_value.fetch_test_cases_by_project.return_value = listed
        runner._db.client.scroll.return_value = _scroll_result(
            [(_point_id("SMOKE-1"), stored_record.content_hash, "2026-01-01T00:00:00+00:00")]
        )

        result = await runner.sync_project(PROJECT_KEY)

        assert result.processed_count == 1
        runner._db.upsert_batch.assert_not_awaited()
        runner._db.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_changed_test_case_is_upserted_again(self, runner):
        listed = [_listed("SMOKE-1")]
        runner._tms.return_value.fetch_test_cases_by_project.return_value = listed
        runner._db.client.scroll.return_value = _scroll_result(
            [(_point_id("SMOKE-1"), "different-hash", "2026-01-01T00:00:00+00:00")]
        )

        await runner.sync_project(PROJECT_KEY)

        upserted = [record for batch in runner._db.upsert_batch.await_args_list for record in batch.args[0]]
        assert [record.test_case_key for record in upserted] == ["SMOKE-1"]

    @pytest.mark.asyncio
    async def test_a_test_case_absent_from_the_listing_is_deleted(self, runner):
        runner._tms.return_value.fetch_test_cases_by_project.return_value = [_listed("SMOKE-1")]
        runner._db.client.scroll.return_value = _scroll_result(
            [
                (_point_id("SMOKE-1"), "anything", "2026-01-01T00:00:00+00:00"),
                (_point_id("SMOKE-GONE"), "anything", "2026-01-01T00:00:00+00:00"),
            ]
        )

        await runner.sync_project(PROJECT_KEY)

        runner._db.delete.assert_awaited_once_with([_point_id("SMOKE-GONE")])

    @pytest.mark.asyncio
    async def test_a_failed_listing_aborts_without_any_deletion(self, runner):
        runner._tms.return_value.fetch_test_cases_by_project.side_effect = RuntimeError("TMS down")
        runner._db.client.scroll.return_value = _scroll_result(
            [(_point_id("SMOKE-1"), "h", "2026-01-01T00:00:00+00:00")]
        )

        with pytest.raises(RuntimeError, match="TMS down"):
            await runner.sync_project(PROJECT_KEY)

        runner._db.upsert_batch.assert_not_awaited()
        runner._db.delete.assert_not_awaited()


class TestIndexedAtGuard:
    @pytest.mark.asyncio
    async def test_a_point_indexed_after_the_run_started_is_never_deleted(self, runner):
        runner._tms.return_value.fetch_test_cases_by_project.return_value = []
        fresh_indexed_at = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
        runner._db.client.scroll.return_value = _scroll_result([(_point_id("SMOKE-FRESH"), "h", fresh_indexed_at)])

        await runner.sync_project(PROJECT_KEY)

        runner._db.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_point_indexed_before_the_run_started_is_deleted_when_absent(self, runner):
        runner._tms.return_value.fetch_test_cases_by_project.return_value = []
        runner._db.client.scroll.return_value = _scroll_result(
            [(_point_id("SMOKE-OLD"), "h", "2026-01-01T00:00:00+00:00")]
        )

        await runner.sync_project(PROJECT_KEY)

        runner._db.delete.assert_awaited_once_with([_point_id("SMOKE-OLD")])


class TestStatusFilter:
    def test_an_empty_filter_indexes_every_status(self):
        listed = [_listed("SMOKE-1", status="Draft"), _listed("SMOKE-2", status="Approved")]
        assert _eligible_for_indexing(listed) == listed

    @pytest.mark.asyncio
    async def test_only_eligible_statuses_are_indexed(self, runner):
        runner._tms.return_value.fetch_test_cases_by_project.return_value = [
            _listed("SMOKE-1", status="Draft"),
            _listed("SMOKE-2", status="Approved"),
        ]
        runner._db.client.scroll.return_value = _scroll_result([])
        with patch("config.QdrantConfig.TEST_CASE_INDEX_STATUSES", ("Approved",)):
            result = await runner.sync_project(PROJECT_KEY)

        assert result.processed_count == 1
        upserted = [record for batch in runner._db.upsert_batch.await_args_list for record in batch.args[0]]
        assert [record.test_case_key for record in upserted] == ["SMOKE-2"]


class TestLocking:
    @pytest.mark.asyncio
    async def test_the_lock_is_released_and_the_runner_closes(self, runner):
        runner._tms.return_value.fetch_test_cases_by_project.return_value = []

        await runner.sync_project(PROJECT_KEY)

        runner._lock_store.release.assert_awaited_once_with(scope_key("test_cases", PROJECT_KEY), "t")
        runner._db.close.assert_awaited_once()
        runner._metadata_db.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_lost_lock_aborts_before_writes(self, runner):
        runner._tms.return_value.fetch_test_cases_by_project.return_value = [_listed("SMOKE-1")]
        runner._db.client.scroll.return_value = _scroll_result([])
        runner._lock_store.is_holder.return_value = False

        with pytest.raises(PermissionError):
            await runner.sync_project(PROJECT_KEY, lock_token="taken")

        runner._db.upsert_batch.assert_not_awaited()

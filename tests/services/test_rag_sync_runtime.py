# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the WS8 sync runtime: lock state machine, sync state, trigger modes.

Every external boundary (Qdrant, Jira, the Cloud Run Admin API, the local sync service)
is mocked; the tests assert the state machine transitions and the endpoint contracts.
"""

import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# The Docker image copies services/rag_sync/ to /app/rag_sync (flat layout); mirror it
# for the tests by putting services/ on the path (rag_sync is a namespace package).
SERVICES_DIR = Path(__file__).resolve().parents[2] / "services"
if str(SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICES_DIR))

import common.services.sync_lock_store as lock_store_module  # noqa: E402
from common.services.sync_lock_store import LOCK_RECORD_KIND, SyncLockStore, SyncStateStore, scope_key  # noqa: E402
from common.services.vector_db_service import VectorDbService  # noqa: E402


@pytest.fixture
def metadata_db():
    """A VectorDbService whose Qdrant client is a recording AsyncMock."""
    with patch("common.services.vector_db_service.AsyncQdrantClient") as mock_client_cls:
        client = AsyncMock()
        mock_client_cls.return_value = client
        db = VectorDbService("rag_metadata")
        db._metadata_db = None  # plain metadata store, no nested identity handling

        # Back the payload-record helpers with an in-memory dict so the lock store
        # can read back its own writes (the mocked Qdrant client doesn't store).
        records: dict[str, dict] = {}

        async def upsert_payload_record(record_id, payload):
            records[record_id] = dict(payload)

        async def get_payload_record(record_id):
            return records.get(record_id)

        async def delete_payload_record(record_id):
            records.pop(record_id, None)

        db.upsert_payload_record = upsert_payload_record
        db.get_payload_record = get_payload_record
        db.delete_payload_record = delete_payload_record
        yield db


@pytest.fixture
def lock_store(metadata_db):
    return SyncLockStore(metadata_db, ttl_seconds=3600, start_allowance_seconds=300)


@pytest.fixture
def state_store(metadata_db):
    return SyncStateStore(metadata_db)


class TestScopeKey:
    def test_scope_keys(self):
        assert scope_key("jira", "PROJ") == "jira:PROJ"
        assert scope_key("confluence", "~dev") == "confluence:~dev"


class TestLockAcquire:
    async def test_acquire_missing_lock_succeeds(self, lock_store, metadata_db):
        state = await lock_store.acquire("jira:PROJ")
        assert state.acquired
        assert state.lock_info["holder_token"]
        assert state.lock_info["started"] is False
        # The record is stored and read back with the holder token.
        stored = await metadata_db.get_payload_record(f"{LOCK_RECORD_KIND}-jira:PROJ")
        assert stored["holder_token"] == state.lock_info["holder_token"]

    async def test_acquire_live_lock_conflicts(self, lock_store, metadata_db):
        first = await lock_store.acquire("jira:PROJ")
        second = await lock_store.acquire("jira:PROJ")
        assert not second.acquired
        assert second.lock_info["holder_token"] == first.lock_info["holder_token"]

    async def test_acquire_expired_lock_is_taken_over(self, lock_store, metadata_db):
        # A stored lock whose expiry lies in the past can be taken over.
        await metadata_db.upsert_payload_record(
            f"{LOCK_RECORD_KIND}-jira:PROJ",
            {"kind": LOCK_RECORD_KIND, "scope": "jira:PROJ", "holder_token": "old",
             "acquired_at": time.time() - 7200, "expires_at": time.time() - 1, "started": True},
        )

        state = await lock_store.acquire("jira:PROJ")
        assert state.acquired
        assert state.lock_info["holder_token"] != "old"

    async def test_acquire_unconfirmed_lock_taken_over_after_start_allowance(self, lock_store, metadata_db):
        original_upsert = metadata_db.upsert_payload_record

        async def _age_acquisition(record_id, payload):
            payload = dict(payload)
            payload["acquired_at"] = time.time() - 400  # beyond the 300s allowance
            await original_upsert(record_id, payload)

        metadata_db.upsert_payload_record = _age_acquisition
        await lock_store.acquire("jira:PROJ")
        metadata_db.upsert_payload_record = original_upsert

        state = await lock_store.acquire("jira:PROJ")
        assert state.acquired

    async def test_acquire_unconfirmed_lock_held_within_start_allowance(self, lock_store, metadata_db):
        await lock_store.acquire("jira:PROJ")
        # Acquired just now, not started, within the allowance: cannot be taken over.
        state = await lock_store.acquire("jira:PROJ")
        assert not state.acquired


class TestLockHolder:
    async def test_is_holder_true_for_token(self, lock_store, metadata_db):
        state = await lock_store.acquire("jira:PROJ")
        assert await lock_store.is_holder("jira:PROJ", state.lock_info["holder_token"])

    async def test_is_holder_false_for_other_token(self, lock_store):
        await lock_store.acquire("jira:PROJ")
        assert not await lock_store.is_holder("jira:PROJ", "someone-else")

    async def test_mark_started_extends_expiry(self, lock_store, metadata_db):
        state = await lock_store.acquire("jira:PROJ")
        before = state.lock_info["expires_at"]
        time.sleep(0.01)

        assert await lock_store.mark_started("jira:PROJ", state.lock_info["holder_token"])

        stored = await metadata_db.get_payload_record(f"{LOCK_RECORD_KIND}-jira:PROJ")
        assert stored["started"] is True
        assert stored["expires_at"] > before

    async def test_mark_started_fails_for_non_holder(self, lock_store):
        await lock_store.acquire("jira:PROJ")
        assert not await lock_store.mark_started("jira:PROJ", "someone-else")

    async def test_release_only_by_holder(self, lock_store, metadata_db):
        await lock_store.acquire("jira:PROJ")
        assert not await lock_store.release("jira:PROJ", "someone-else")
        metadata_db.client.delete.assert_not_called()


class TestSyncState:
    async def test_cursor_roundtrip(self, state_store, metadata_db):
        await state_store.save_cursor("jira:PROJ", {"last_update": "2026-01-01T00:00:00Z", "processed_count": 3})
        cursor = await state_store.get_cursor("jira:PROJ")
        assert cursor["last_update"] == "2026-01-01T00:00:00Z"
        assert cursor["processed_count"] == 3

    async def test_reset_clears_cursor(self, state_store, metadata_db):
        await state_store.save_cursor("jira:PROJ", {"last_update": "x"})
        await state_store.reset("jira:PROJ")
        assert await state_store.get_cursor("jira:PROJ") is None

    async def test_get_missing_cursor_returns_none(self, state_store):
        assert await state_store.get_cursor("jira:NOPE") is None


class TestJiraRunner:
    """The Jira sync runner's lock and cursor behaviour (WS8)."""

    @pytest.fixture
    def runner(self, metadata_db):
        with (
            patch("rag_sync.jira_sync.VectorDbService") as mock_vdb,
            patch("rag_sync.jira_sync.SyncLockStore") as mock_lock_cls,
            patch("rag_sync.jira_sync.SyncStateStore") as mock_state_cls,
        ):
            issues_db = MagicMock()
            issues_db.close = AsyncMock()
            issues_db.ensure_collection = AsyncMock()
            issues_db.upsert_batch = AsyncMock()
            issues_db.delete = AsyncMock()
            issues_db.scroll_all_ids_by_project = AsyncMock(return_value=[])
            issues_db.has_points = AsyncMock(return_value=True)
            mock_vdb.side_effect = [issues_db, metadata_db]

            lock_store = MagicMock()
            mock_lock_cls.return_value = lock_store

            state_store = MagicMock()
            metadata_db.close = AsyncMock()
            state_store.get_cursor = AsyncMock(return_value=None)
            state_store.save_cursor = AsyncMock()
            state_store.reset = AsyncMock()
            mock_state_cls.return_value = state_store

            from rag_sync.jira_sync import JiraRagSyncRunner

            runner = JiraRagSyncRunner()
            runner._lock_store = lock_store
            runner._state_store = state_store
            runner._issues_db = issues_db
            yield runner, issues_db, lock_store, state_store

    @staticmethod
    def _issue(issue_id=1, status="To Do"):
        from common.models import JiraIssue

        return JiraIssue(
            id=issue_id, key=f"PROJ-{issue_id}", summary="s", description="d",
            issue_type="Story", status=status, project_key="PROJ",
        )

    async def test_token_runner_marks_started_and_releases(self, runner):
        runner_obj, _, lock_store, _ = runner
        lock_store.mark_started = AsyncMock(return_value=True)
        lock_store.is_holder = AsyncMock(return_value=True)
        lock_store.release = AsyncMock(return_value=True)

        with patch.object(runner_obj, "_create_jira_client", return_value=MagicMock()), \
             patch.object(runner_obj, "_fetch_issues_updated_since", return_value=[]), \
             patch.object(runner_obj, "_get_last_update_timestamp", AsyncMock(return_value="1970-01-01T00:00:00Z")):
            result = await runner_obj.sync_project("PROJ", lock_token="tok")

        assert result.status == "completed"
        lock_store.mark_started.assert_awaited_once_with("jira:PROJ", "tok")
        lock_store.release.assert_awaited_once_with("jira:PROJ", "tok")

    async def test_taken_over_runner_aborts_before_writes(self, runner):
        runner_obj, issues_db, lock_store, _ = runner
        lock_store.mark_started = AsyncMock(return_value=False)

        with pytest.raises(PermissionError):
            await runner_obj.sync_project("PROJ", lock_token="stale")
        issues_db.upsert_batch.assert_not_called()

    async def test_cursor_saved_as_run_start_minus_delay(self, runner):
        """The WS8 fix: the saved cursor is the run's start time minus the overlap delay,
        so an issue updated during the run is fetched by the next run."""
        runner_obj, _, lock_store, state_store = runner
        lock_store.mark_started = AsyncMock(return_value=True)
        lock_store.is_holder = AsyncMock(return_value=True)
        lock_store.release = AsyncMock(return_value=True)

        run_started = time.time()
        with patch.object(runner_obj, "_create_jira_client", return_value=MagicMock()), \
             patch.object(runner_obj, "_fetch_issues_updated_since", return_value=[]), \
             patch.object(runner_obj, "_get_last_update_timestamp", AsyncMock(return_value="1970-01-01T00:00:00Z")), \
             patch("rag_sync.jira_sync.EXECUTION_DELAY_SECONDS", 60):
            await runner_obj.sync_project("PROJ", lock_token="tok")

        call = state_store.save_cursor.call_args
        saved = call.args[1]["last_update"]
        from datetime import UTC, datetime

        # The stored timestamp is UTC; parse it as UTC so the epoch comparison is sound.
        saved_dt = datetime.strptime(saved, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
        assert 55 <= run_started - saved_dt <= 65, (
            f"Saved cursor {saved} should be run start {run_started} minus ~60s"
        )

    async def test_holder_checked_between_write_batches(self, runner):
        runner_obj, issues_db, lock_store, _ = runner
        lock_store.mark_started = AsyncMock(return_value=True)
        # First check passes, the second (before the write batch) fails.
        lock_store.is_holder = AsyncMock(side_effect=[True, False, True, True, True])
        lock_store.release = AsyncMock(return_value=True)

        with patch.object(runner_obj, "_create_jira_client", return_value=MagicMock()), \
             patch.object(runner_obj, "_fetch_issues_updated_since", return_value=[self._issue()]), \
             patch.object(runner_obj, "_get_last_update_timestamp", AsyncMock(return_value="1970-01-01T00:00:00Z")), \
             pytest.raises(PermissionError):
            await runner_obj.sync_project("PROJ", lock_token="tok")
        issues_db.upsert_batch.assert_not_called()

    async def test_project_without_stored_issues_resets_cursor_and_legacy_watermark(self, runner, metadata_db):
        """The issues collection is shared: after another project's sync recreated it, this project's
        cursor and legacy watermark must not survive and skip its unchanged issues (WS7 migration)."""
        from common.models import ProjectMetadata

        runner_obj, issues_db, lock_store, state_store = runner
        runner_obj._metadata_db = metadata_db
        legacy_id = ProjectMetadata(project_key="PROJ", last_update="1970-01-01T00:00:00Z").get_vector_id()
        await metadata_db.upsert_payload_record(legacy_id, {"last_update": "2026-01-01T00:00:00Z"})
        issues_db.has_points = AsyncMock(return_value=False)
        lock_store.mark_started = AsyncMock(return_value=True)
        lock_store.is_holder = AsyncMock(return_value=True)
        lock_store.release = AsyncMock(return_value=True)

        with patch.object(runner_obj, "_create_jira_client", return_value=MagicMock()), \
             patch.object(runner_obj, "_fetch_all_issue_ids", return_value=[]), \
             patch.object(runner_obj, "_fetch_issues_updated_since", return_value=[]) as fetch_issues:
            await runner_obj.sync_project("PROJ", lock_token="tok")

        project_condition = issues_db.has_points.await_args.args[0].must[0]
        assert (project_condition.key, project_condition.match.value) == ("project_key", "PROJ")
        state_store.reset.assert_awaited_once_with("jira:PROJ")
        assert await metadata_db.get_payload_record(legacy_id) is None
        assert fetch_issues.call_args.args[2] == "1970-01-01T00:00:00Z"

    async def test_project_with_stored_issues_keeps_the_cursor(self, runner):
        runner_obj, _, lock_store, state_store = runner
        lock_store.mark_started = AsyncMock(return_value=True)
        lock_store.is_holder = AsyncMock(return_value=True)
        lock_store.release = AsyncMock(return_value=True)

        with patch.object(runner_obj, "_create_jira_client", return_value=MagicMock()), \
             patch.object(runner_obj, "_fetch_issues_updated_since", return_value=[]), \
             patch.object(runner_obj, "_get_last_update_timestamp", AsyncMock(return_value="1970-01-01T00:00:00Z")):
            await runner_obj.sync_project("PROJ", lock_token="tok")

        state_store.reset.assert_not_awaited()

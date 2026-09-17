# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Full-resync synchronization of test cases into the RAG vector database (WS17).

Unlike the Jira sync there is no cursor: the test-management systems offer no cheap
"changed since" query, so every run lists the whole project, upserts new and changed test
cases (an unchanged content hash skips the re-embedding) and deletes stored points that
vanished from the listing. A point that was indexed after this run started (a review
indexing a brand-new test case mid-run) is never deleted. A failed listing aborts the run
before any write, so the stored index can never lose points it should have kept.
"""

import asyncio
from datetime import UTC, datetime

from qdrant_client import models

import config
from common import utils
from common.models import ListedTestCase, RagUpdateResult
from common.services.sync_lock_store import SyncLockStore, scope_key
from common.services.test_case_index import render_test_case
from common.services.test_management_system_client_provider import get_test_management_client
from common.services.vector_db_service import VectorDbService

logger = utils.get_logger("rag_sync")

TEST_CASES_SCOPE = "test_cases"


class TestCaseRagSyncRunner:
    """Runs one test-case resync for one project to completion, honouring the scope lock."""

    def __init__(self) -> None:
        self._metadata_db = VectorDbService(config.QdrantConfig.METADATA_COLLECTION_NAME)
        self._test_cases_db = VectorDbService(
            config.QdrantConfig.TEST_CASES_COLLECTION_NAME,
            metadata_db=self._metadata_db,
        )
        self._lock_store = SyncLockStore(
            self._metadata_db,
            ttl_seconds=config.RagSyncConfig.LOCK_TTL_SECONDS,
            start_allowance_seconds=config.RagSyncConfig.START_ALLOWANCE_SECONDS,
        )

    async def close(self) -> None:
        await self._test_cases_db.close()
        await self._metadata_db.close()

    async def sync_project(self, project_key: str, lock_token: str | None = None) -> RagUpdateResult:
        """Re-synchronizes the test cases of the given project into the vector DB.

        A runner started without a token (a manual CLI run or a direct call to the local
        service) acquires the lock itself; an orchestrator-started runner receives the token
        and verifies it holds the lock before every write.

        Raises:
            PermissionError: When the runner no longer holds the lock at a write point.
            RuntimeError: When a tokenless runner cannot acquire the lock.
        """
        scope = scope_key(TEST_CASES_SCOPE, project_key)
        if lock_token:
            if not await self._lock_store.mark_started(scope, lock_token):
                logger.warning(f"Runner no longer holds the lock for {scope}; aborting without writes.")
                raise PermissionError(f"Lock for scope {scope} was taken over before the run started.")
        else:
            state = await self._lock_store.acquire(scope)
            if not state.acquired:
                raise RuntimeError(f"Another sync already holds the lock for {scope}.")
            lock_token = state.lock_info["holder_token"]

        try:
            return await self._run_sync(project_key, scope, lock_token)
        finally:
            released = await self._lock_store.release(scope, lock_token)
            if not released:
                logger.warning(f"Lock for {scope} was not released by this runner; it was taken over.")
            await self.close()

    async def _run_sync(self, project_key: str, scope: str, lock_token: str) -> RagUpdateResult:
        logger.info(f"Starting test-case RAG sync for project {project_key}.")
        run_started = datetime.now(UTC)

        # A failed listing raises before any write, leaving the stored index untouched.
        client = get_test_management_client()
        listed = await asyncio.to_thread(client.fetch_test_cases_by_project, project_key)
        eligible = _eligible_for_indexing(listed)
        logger.info(
            f"Listed {len(listed)} test case(s), {len(eligible)} eligible for indexing "
            f"(status filter: {config.QdrantConfig.TEST_CASE_INDEX_STATUSES or 'all'})."
        )
        rendered = [render_test_case(project_key, item) for item in eligible]

        stored = await self._scroll_stored(project_key)
        current_ids = {record.get_vector_id() for record in rendered}

        changed = [record for record in rendered if stored.get(record.get_vector_id(), {}).get("hash") != record.content_hash]
        await self._verify_holder_or_abort(scope, lock_token)
        await self._test_cases_db.ensure_collection()
        for start in range(0, len(changed), config.QdrantConfig.UPSERT_BATCH_SIZE):
            batch = changed[start : start + config.QdrantConfig.UPSERT_BATCH_SIZE]
            await self._verify_holder_or_abort(scope, lock_token)
            await self._test_cases_db.upsert_batch(batch, ensure=False)
        logger.info(f"Upserted {len(changed)} new or changed test case(s) for project {project_key}.")

        stale_ids = [
            point_id
            for point_id, record in stored.items()
            if point_id not in current_ids and _indexed_before(record, run_started)
        ]
        if stale_ids:
            await self._verify_holder_or_abort(scope, lock_token)
            await self._test_cases_db.delete(stale_ids)
            logger.info(f"Deleted {len(stale_ids)} stale test case(s) for project {project_key}.")

        logger.info(f"Test-case RAG sync for project {project_key} completed; indexed {len(rendered)}.")
        return RagUpdateResult(status="completed", processed_count=len(rendered))

    async def _verify_holder_or_abort(self, scope: str, lock_token: str) -> None:
        """Stops at once, without further writes, when the runner no longer holds the lock."""
        if not await self._lock_store.is_holder(scope, lock_token):
            raise PermissionError(f"Lock for scope {scope} was taken over; this run stops without further writes.")

    async def _scroll_stored(self, project_key: str) -> dict[str, dict]:
        """The stored (content hash, indexed_at) per point id, for one project, payload-only."""
        stored: dict[str, dict] = {}
        offset = None
        project_filter = models.Filter(
            must=[
                models.FieldCondition(key="project_key", match=models.MatchValue(value=project_key)),
                models.FieldCondition(key="source", match=models.MatchValue(value="test_case")),
            ]
        )
        while True:
            points, next_offset = await self._test_cases_db.client.scroll(
                collection_name=self._test_cases_db.collection_name,
                scroll_filter=project_filter,
                limit=1000,
                offset=offset,
                with_payload=models.PayloadSelectorInclude(include=["content_hash", "indexed_at"]),
                with_vectors=False,
            )
            for point in points:
                stored[str(point.id)] = {
                    "hash": (point.payload or {}).get("content_hash"),
                    "indexed_at": (point.payload or {}).get("indexed_at"),
                }
            if next_offset is None:
                return stored
            offset = next_offset


def _eligible_for_indexing(listed: list[ListedTestCase]) -> list[ListedTestCase]:
    """Applies the configured status filter; an empty filter indexes every status."""
    allowed = config.QdrantConfig.TEST_CASE_INDEX_STATUSES
    if not allowed:
        return listed
    return [item for item in listed if item.status in allowed]


def _indexed_before(record: dict, run_started: datetime) -> bool:
    """Whether the stored point was indexed before this run started (the deletion guard)."""
    indexed_at = record.get("indexed_at")
    if not indexed_at:
        return True
    try:
        return datetime.fromisoformat(indexed_at) < run_started
    except ValueError:
        logger.warning(f"Stored test-case point has an unparsable indexed_at ({indexed_at!r}); treating as stale.")
        return True

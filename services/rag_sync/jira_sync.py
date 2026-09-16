# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Programmatic synchronization of Jira issues into the RAG vector database (WS8).

The algorithm is unchanged from the former in-orchestrator service, apart from the
cursor fix: the saved cursor is the run's start time minus the overlap delay, taken
BEFORE the run queries Jira, so issues updated during the run are fetched by the next
run. The runner also verifies the scope lock before every write batch and before
saving the cursor, and never saves the cursor when items failed.
"""

import asyncio
import time
from datetime import datetime

from jira import JIRA
from jira.resources import Issue

import config
from common import utils
from common.models import JiraIssue, ProjectMetadata, RagUpdateResult
from common.services.sync_lock_store import SyncLockStore, SyncStateStore, scope_key
from common.services.vector_db_service import VectorDbService

logger = utils.get_logger("rag_sync")

# Subtracted from the run start when persisting the cursor, so issues updated during
# the sync run are not skipped by the next run's "updated >= timestamp" query.
EXECUTION_DELAY_SECONDS = 60
DEFAULT_LAST_UPDATE = "1970-01-01T00:00:00Z"
STORAGE_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
JQL_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"

JIRA_SCOPE = "jira"


def _to_jql_timestamp(stored_timestamp: str) -> str:
    """Convert a stored ISO 8601 timestamp into the 'YYYY-MM-DD HH:mm' format JQL expects."""
    parsed = datetime.strptime(stored_timestamp, STORAGE_TIMESTAMP_FORMAT)
    return parsed.strftime(JQL_TIMESTAMP_FORMAT)


class JiraRagSyncRunner:
    """Runs one Jira sync for one project to completion, honouring the scope lock."""

    def __init__(self) -> None:
        # One shared metadata service: the issues db records/checks the model identity of
        # its vectors through it (WS6), and the lock/state stores write to the same collection.
        self._metadata_db = VectorDbService(config.QdrantConfig.METADATA_COLLECTION_NAME)
        self._issues_db = VectorDbService(
            config.QdrantConfig.TICKETS_COLLECTION_NAME,
            metadata_db=self._metadata_db,
        )
        self._lock_store = SyncLockStore(
            self._metadata_db,
            ttl_seconds=config.RagSyncConfig.LOCK_TTL_SECONDS,
            start_allowance_seconds=config.RagSyncConfig.START_ALLOWANCE_SECONDS,
        )
        self._state_store = SyncStateStore(self._metadata_db)
        self._valid_statuses = set(config.QdrantConfig.VALID_STATUSES)

    async def close(self) -> None:
        await self._issues_db.close()
        await self._metadata_db.close()

    async def sync_project(self, project_key: str, lock_token: str | None = None) -> RagUpdateResult:
        """Synchronizes all Jira issues for the given project into the vector DB.

        A runner started without a token (a manual CLI run or a direct call to the
        local service) acquires the lock itself; an orchestrator-started runner
        receives the token and verifies it holds the lock before every write.

        Args:
            project_key: The Jira project key to synchronize.
            lock_token: The holder token issued by the orchestrator, if any.

        Returns:
            A RagUpdateResult describing the outcome and the number of processed issues.

        Raises:
            PermissionError: When the runner no longer holds the lock at a write point.
            RuntimeError: When a tokenless runner cannot acquire the lock.
        """
        scope = scope_key(JIRA_SCOPE, project_key)
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
        logger.info(f"Starting RAG sync for project {project_key}.")
        # The cursor is taken at run start, BEFORE querying Jira (the WS8 fix).
        run_started_epoch = time.time()
        jira_client = await asyncio.to_thread(self._create_jira_client)

        await self._verify_holder_or_abort(scope, lock_token)
        await self._reconcile_deleted_issues(jira_client, project_key, scope, lock_token)

        last_update = await self._get_last_update_timestamp(project_key)
        issues = await asyncio.to_thread(self._fetch_issues_updated_since, jira_client, project_key, last_update)
        logger.info(f"Fetched {len(issues)} issue(s) updated since {last_update} for project {project_key}.")

        await self._verify_holder_or_abort(scope, lock_token)
        processed_count = await self._sync_issues(issues, scope, lock_token)

        await self._verify_holder_or_abort(scope, lock_token)
        # The cursor is written only on a clean run; the saved value is the run's start
        # time minus the overlap delay, so edits during the run are re-fetched next time.
        cursor_timestamp = time.strftime(
            STORAGE_TIMESTAMP_FORMAT, time.gmtime(run_started_epoch - EXECUTION_DELAY_SECONDS)
        )
        await self._state_store.save_cursor(
            scope, {"last_update": cursor_timestamp, "processed_count": processed_count}
        )

        logger.info(f"RAG sync for project {project_key} completed; processed {processed_count} issue(s).")
        return RagUpdateResult(status="completed", processed_count=processed_count)

    async def _verify_holder_or_abort(self, scope: str, lock_token: str) -> None:
        """Stops at once, without further writes, when the runner no longer holds the lock."""
        if not await self._lock_store.is_holder(scope, lock_token):
            raise PermissionError(f"Lock for scope {scope} was taken over; this run stops without further writes.")

    async def _reconcile_deleted_issues(self, jira_client: JIRA, project_key: str, scope: str, lock_token: str) -> None:
        """Deletes from the vector DB any issues that no longer exist in Jira."""
        current_ids = await asyncio.to_thread(self._fetch_all_issue_ids, jira_client, project_key)
        stored_ids = await self._issues_db.scroll_all_ids_by_project(project_key)
        stale_ids = list(set(stored_ids) - set(current_ids))
        if stale_ids:
            await self._verify_holder_or_abort(scope, lock_token)
            await self._issues_db.delete(stale_ids)
            logger.info(f"Deleted {len(stale_ids)} stale issue(s) for project {project_key}.")

    async def _sync_issues(self, issues: list[JiraIssue], scope: str, lock_token: str) -> int:
        """Upserts active issues and deletes inactive ones, returning the number processed."""
        if not issues:
            return 0
        await self._issues_db.ensure_collection()
        active_issues = [issue for issue in issues if issue.status in self._valid_statuses]
        inactive_ids = [issue.id for issue in issues if issue.status not in self._valid_statuses]
        # The lock is verified before every write batch (upsert_batch batches internally).
        for start in range(0, len(active_issues), config.QdrantConfig.UPSERT_BATCH_SIZE):
            batch = active_issues[start : start + config.QdrantConfig.UPSERT_BATCH_SIZE]
            await self._verify_holder_or_abort(scope, lock_token)
            await self._issues_db.upsert_batch(batch, ensure=False)
        if inactive_ids:
            await self._verify_holder_or_abort(scope, lock_token)
            await self._issues_db.delete(inactive_ids)
        return len(issues)

    async def _get_last_update_timestamp(self, project_key: str) -> str:
        scope = scope_key(JIRA_SCOPE, project_key)
        cursor = await self._state_store.get_cursor(scope)
        if cursor:
            return cursor.get("last_update", DEFAULT_LAST_UPDATE)
        # Backwards compatibility: fall back to the legacy ProjectMetadata record.
        legacy_id = ProjectMetadata(project_key=project_key, last_update=DEFAULT_LAST_UPDATE).get_vector_id()
        record = await self._metadata_db.get_payload_record_if_exists(legacy_id)
        if record:
            return record.get("last_update", DEFAULT_LAST_UPDATE)
        return DEFAULT_LAST_UPDATE

    @staticmethod
    def _create_jira_client() -> JIRA:
        from common.services.jira_client import build_jira_client

        return build_jira_client()

    @staticmethod
    def _fetch_all_issue_ids(jira_client: JIRA, project_key: str) -> list[int]:
        jql = f'project = "{project_key}"'
        issues = jira_client.search_issues(jql, fields="id", maxResults=False)
        return [int(issue.id) for issue in issues]

    def _fetch_issues_updated_since(self, jira_client: JIRA, project_key: str, last_update: str) -> list[JiraIssue]:
        jql = f'project = "{project_key}" AND updated >= "{_to_jql_timestamp(last_update)}"'
        issues = jira_client.search_issues(
            jql, fields="summary,description,status,issuetype,updated", maxResults=False
        )
        return [self._to_jira_issue(issue, project_key) for issue in issues]

    @staticmethod
    def _to_jira_issue(issue: Issue, project_key: str) -> JiraIssue:
        fields = issue.fields
        return JiraIssue(
            id=int(issue.id),
            key=issue.key,
            summary=fields.summary or "",
            description=fields.description or "",
            issue_type=fields.issuetype.name,
            status=fields.status.name,
            project_key=project_key,
            updated_at=fields.updated,
        )

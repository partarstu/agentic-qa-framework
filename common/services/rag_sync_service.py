# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Programmatic synchronization of Jira issues into the RAG vector database.

This replaces the former Jira RAG Update Agent: the sync algorithm is fully deterministic,
so it runs directly against the Jira REST API (via the ``jira`` client) and the vector DB,
without invoking an LLM.
"""

import asyncio
import time
from datetime import datetime

from jira import JIRA
from jira.resources import Issue

import config
from common import utils
from common.models import JiraIssue, ProjectMetadata, RagUpdateResult
from common.services.vector_db_service import VectorDbService

logger = utils.get_logger("rag_sync_service")

# Subtracted from "now" when persisting the last-update timestamp, so issues updated during the
# sync run are not skipped by the next run's "updated >= timestamp" query.
EXECUTION_DELAY_SECONDS = 60
DEFAULT_LAST_UPDATE = "1970-01-01T00:00:00Z"
_STORAGE_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_JQL_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"


def _to_jql_timestamp(stored_timestamp: str) -> str:
    """Convert a stored ISO 8601 timestamp into the 'YYYY-MM-DD HH:mm' format JQL expects."""
    parsed = datetime.strptime(stored_timestamp, _STORAGE_TIMESTAMP_FORMAT)
    return parsed.strftime(_JQL_TIMESTAMP_FORMAT)


class JiraRagSyncService:
    """Keeps the RAG vector DB in sync with a Jira project's issues."""

    def __init__(self) -> None:
        self._issues_db = VectorDbService(config.QdrantConfig.TICKETS_COLLECTION_NAME)
        self._metadata_db = VectorDbService(config.QdrantConfig.METADATA_COLLECTION_NAME)
        self._valid_statuses = set(config.QdrantConfig.VALID_STATUSES)

    async def sync_project(self, project_key: str) -> RagUpdateResult:
        """Synchronizes all Jira issues for the given project into the vector DB.

        The steps mirror the former agent's workflow: reconcile issues deleted in Jira, fetch
        everything changed since the last run, upsert active issues / delete inactive ones, and
        persist the new watermark timestamp.

        Args:
            project_key: The Jira project key to synchronize.

        Returns:
            A RagUpdateResult describing the outcome and the number of processed issues.
        """
        logger.info(f"Starting RAG sync for project {project_key}.")
        jira_client = await asyncio.to_thread(self._create_jira_client)

        await self._reconcile_deleted_issues(jira_client, project_key)

        last_update = await self._get_last_update_timestamp(project_key)
        issues = await asyncio.to_thread(self._fetch_issues_updated_since, jira_client, project_key, last_update)
        logger.info(f"Fetched {len(issues)} issue(s) updated since {last_update} for project {project_key}.")

        processed_count = await self._sync_issues(issues)
        await self._save_last_update_timestamp(project_key)

        logger.info(f"RAG sync for project {project_key} completed; processed {processed_count} issue(s).")
        return RagUpdateResult(status="completed", processed_count=processed_count)

    @staticmethod
    def _create_jira_client() -> JIRA:
        if not config.JIRA_BASE_URL or not config.JIRA_USER or not config.JIRA_TOKEN:
            raise RuntimeError("Jira configuration is missing (JIRA_URL, JIRA_USERNAME, or JIRA_API_TOKEN).")
        return JIRA(server=config.JIRA_BASE_URL, basic_auth=(config.JIRA_USER, config.JIRA_TOKEN))

    async def _reconcile_deleted_issues(self, jira_client: JIRA, project_key: str) -> None:
        """Deletes from the vector DB any issues that no longer exist in Jira."""
        current_ids = await asyncio.to_thread(self._fetch_all_issue_ids, jira_client, project_key)
        stored_ids = await self._issues_db.scroll_all_ids_by_project(project_key)
        stale_ids = list(set(stored_ids) - set(current_ids))
        if stale_ids:
            await self._issues_db.delete(stale_ids)
            logger.info(f"Deleted {len(stale_ids)} stale issue(s) for project {project_key}.")

    async def _sync_issues(self, issues: list[JiraIssue]) -> int:
        """Upserts active issues and deletes inactive ones, returning the number processed."""
        if not issues:
            return 0
        await self._issues_db.ensure_collection()
        active_issues = [issue for issue in issues if issue.status in self._valid_statuses]
        inactive_ids = [issue.id for issue in issues if issue.status not in self._valid_statuses]
        await asyncio.gather(*(self._issues_db.upsert(data=issue, ensure=False) for issue in active_issues))
        if inactive_ids:
            await self._issues_db.delete(inactive_ids)
        return len(issues)

    async def _get_last_update_timestamp(self, project_key: str) -> str:
        project_id = ProjectMetadata(project_key=project_key, last_update=DEFAULT_LAST_UPDATE).get_vector_id()
        points = await self._metadata_db.retrieve(point_ids=[project_id])
        if points and points[0].payload:
            return points[0].payload.get("last_update", DEFAULT_LAST_UPDATE)
        return DEFAULT_LAST_UPDATE

    async def _save_last_update_timestamp(self, project_key: str) -> None:
        timestamp = time.strftime(_STORAGE_TIMESTAMP_FORMAT, time.gmtime(time.time() - EXECUTION_DELAY_SECONDS))
        await self._metadata_db.upsert(data=ProjectMetadata(project_key=project_key, last_update=timestamp))

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


_service: JiraRagSyncService | None = None


def get_rag_sync_service() -> JiraRagSyncService:
    """Returns the lazily-created singleton sync service (avoids import-time vector DB clients)."""
    global _service
    if _service is None:
        _service = JiraRagSyncService()
    return _service

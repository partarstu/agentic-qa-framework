# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0
import time

from pydantic_ai.mcp import MCPServerSSE
from qdrant_client import models as qdrant_models

import config
from agents.jira_rag.prompt import JiraRagUpdateSystemPrompt
from common import utils
from common.agent_base import AgentBase
from common.models import JiraIssue, ProjectMetadata, RagUpdateResult
from common.services.vector_db_service import VectorDbService

logger = utils.get_logger("jira_rag_update_agent")

EXECUTION_DELAY_SECONDS = 60
DEFAULT_LAST_UPDATE = "1970-01-01T00:00:00Z"
RAG_COLLECTION = getattr(config.QdrantConfig, "TICKETS_COLLECTION_NAME", "jira_issues")
METADATA_COLLECTION = getattr(config.QdrantConfig, "METADATA_COLLECTION_NAME", "rag_metadata")
VALID_STATUSES = getattr(config.QdrantConfig, "VALID_STATUSES", ["To Do", "In Progress", "Done"])
BUG_ISSUE_TYPE = getattr(config.QdrantConfig, "BUG_ISSUE_TYPE", "Bug")

jira_mcp_server = MCPServerSSE(url=config.JIRA_MCP_SERVER_URL, timeout=config.MCP_SERVER_TIMEOUT_SECONDS)


class JiraRagAgent(AgentBase):
    def __init__(self):
        self.issues_db = VectorDbService(RAG_COLLECTION)
        self.metadata_db = VectorDbService(METADATA_COLLECTION)

        instruction_prompt = JiraRagUpdateSystemPrompt(
            valid_statuses=VALID_STATUSES
        )

        super().__init__(
            agent_name=config.JiraRagUpdateAgentConfig.OWN_NAME,
            base_url=config.AGENT_BASE_URL,
            port=config.JiraRagUpdateAgentConfig.PORT,
            external_port=config.JiraRagUpdateAgentConfig.EXTERNAL_PORT,
            protocol=config.JiraRagUpdateAgentConfig.PROTOCOL,
            model_name=config.JiraRagUpdateAgentConfig.MODEL_NAME,
            output_type=RagUpdateResult,
            instructions=instruction_prompt.get_prompt(),
            mcp_servers=[jira_mcp_server],
            description="Agent responsible for keeping the RAG Vector DB up-to-date with Jira issues.",
            tools=[
                self.get_last_update_timestamp,
                self.save_last_update_timestamp,
                self.upsert_issues,
                self.delete_issues,
                self.search_issues,
            ]
        )

    def get_thinking_budget(self) -> int:
        return config.JiraRagUpdateAgentConfig.THINKING_BUDGET

    def get_max_requests_per_task(self) -> int:
        return config.JiraRagUpdateAgentConfig.MAX_REQUESTS_PER_TASK

    @staticmethod
    def _key_to_int(key: str) -> int:
        """Convert a project key to an integer ID for ProjectMetadata storage.
        """
        import hashlib
        return int(hashlib.md5(key.encode()).hexdigest()[:16], 16)

    async def get_last_update_timestamp(self, project_key: str) -> str:
        """Retrieves the timestamp of the last project update from the metadata DB.

        Args:
            project_key: The key of the project for which the timestamp needs to be retrieved.
        """
        try:
            project_new_id = self._key_to_int(project_key)
            points = await self.metadata_db.retrieve(point_ids=[project_new_id])
            if points and points[0].payload:
                return points[0].payload.get("last_update", DEFAULT_LAST_UPDATE)
            return DEFAULT_LAST_UPDATE
        except Exception:
            logger.exception("Error fetching last update")
            raise

    async def save_last_update_timestamp(self, project_key: str) -> str:
        """Saves the current timestamp as the last project update timestamp in the metadata DB.

         Args:
            project_key: The key of the project for which the current timestamp needs to be saved.
        """
        try:
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - EXECUTION_DELAY_SECONDS))
            metadata = ProjectMetadata(project_key=project_key, last_update=timestamp)
            await self.metadata_db.upsert(data=metadata)
            return "Timestamp saved."
        except Exception:
            logger.exception("Error saving last update")
            raise

    async def upsert_issues(self, issues: list[JiraIssue]) -> str:
        """Upserts a list of Jira issues into the vector DB.

         Args:
            issues: The list of Jira issues which need to be upserted.
        """
        count = 0
        try:
            for issue in issues:
                await self.issues_db.upsert(data=issue)
                count += 1
            return f"Upserted {count} issues."
        except Exception:
            logger.exception("Error upserting issues")
            raise

    async def delete_issues(self, issue_ids: list[int]) -> str:
        """Deletes a list of Jira issues from the vector DB by their numeric IDs."""
        try:
            if not issue_ids:
                return "No issues to delete."
            await self.issues_db.delete(issue_ids)
            return f"Deleted {len(issue_ids)} issues."
        except Exception:
            logger.exception("Error deleting issues")
            raise

    async def search_issues(
            self,
            query_text: str,
            limit: int = 10,
            score_threshold: float = 0.7,
            issue_type: str | None = None,
            status: str | None = None,
            project_key: str | None = None,
            updated_after: str | None = None,
            updated_before: str | None = None,
    ) -> list[dict]:
        """Searches for Jira issues in the vector DB with optional payload filters.

        Args:
            query_text: The semantic search query text.
            limit: Maximum number of results to return (default: 10).
            score_threshold: Minimum similarity score (default: 0.7).
            issue_type: Filter by issue type (e.g., 'Bug', 'Story', 'Task').
            status: Filter by issue status (e.g., 'To Do', 'In Progress', 'Done').
            project_key: Filter by project key.
            updated_after: Filter issues updated after this datetime (ISO 8601 format, e.g., '2025-01-15T00:00:00Z').
            updated_before: Filter issues updated before this datetime (ISO 8601 format).

        Returns:
            List of matching issues with their payload data and similarity scores.
        """
        try:
            conditions = []

            if issue_type:
                conditions.append(
                    qdrant_models.FieldCondition(
                        key="issue_type",
                        match=qdrant_models.MatchValue(value=issue_type),
                    )
                )

            if status:
                conditions.append(
                    qdrant_models.FieldCondition(
                        key="status",
                        match=qdrant_models.MatchValue(value=status),
                    )
                )

            if project_key:
                conditions.append(
                    qdrant_models.FieldCondition(
                        key="project_key",
                        match=qdrant_models.MatchValue(value=project_key),
                    )
                )

            # Datetime range filter for updated_at
            if updated_after or updated_before:
                conditions.append(
                    qdrant_models.FieldCondition(
                        key="updated_at",
                        range=qdrant_models.DatetimeRange(
                            gte=updated_after,
                            lte=updated_before,
                        ),
                    )
                )

            # Create filter only if there are conditions
            query_filter = qdrant_models.Filter(must=conditions) if conditions else None

            points = await self.issues_db.search(
                query_text=query_text,
                limit=limit,
                score_threshold=score_threshold,
                query_filter=query_filter,
            )

            # Format results
            results = []
            for point in points:
                payload = point.payload or {}
                results.append({
                    "id": point.id,
                    "key": payload.get("key"),
                    "summary": payload.get("summary"),
                    "description": payload.get("description"),
                    "issue_type": payload.get("issue_type"),
                    "status": payload.get("status"),
                    "project_key": payload.get("project_key"),
                    "updated_at": payload.get("updated_at"),
                    "score": point.score,
                })

            return results
        except Exception:
            logger.exception("Error searching issues")
            raise


agent = JiraRagAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()

# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from typing import List

from pydantic_ai.mcp import MCPServerSSE

import config
from common import utils
from common.agent_base import AgentBase
from common.services.vector_db_service import VectorDbService
from common.models import JsonSerializableModel, JiraIssue

logger = utils.get_logger("jira_rag_update_agent")

RAG_COLLECTION = getattr(config.QdrantConfig, "COLLECTION_NAME", "jira_issues")
METADATA_COLLECTION = getattr(config.QdrantConfig, "METADATA_COLLECTION_NAME", "rag_metadata")
VALID_STATUSES = getattr(config.QdrantConfig, "VALID_STATUSES", ["To Do", "In Progress", "Done"])
BUG_ISSUE_TYPE = getattr(config.QdrantConfig, "BUG_ISSUE_TYPE", "Bug")

jira_mcp_server = MCPServerSSE(url=config.JIRA_MCP_SERVER_URL, timeout=config.MCP_SERVER_TIMEOUT_SECONDS)


class RagUpdateResult(JsonSerializableModel):
    status: str
    processed_count: int


class JiraRagUpdateAgent(AgentBase):
    def __init__(self):
        self.issues_db = VectorDbService(RAG_COLLECTION)
        self.metadata_db = VectorDbService(METADATA_COLLECTION)
        
        instruction_prompt = (
            f"You are an agent responsible for keeping the RAG Vector DB up-to-date with Jira issues.\n"
            f"Your task is to sync bugs for a specific project based on the user request.\n"
            f"1. Extract the `project_key` from the user request.\n"
            f"2. Get the last update timestamp using `get_last_update_timestamp(project_key)`.\n"
            f"3. Search Jira (using available MCP tools) for issues in the project that were CREATED or UPDATED after the timestamp.\n"
            f"   - Use JQL to find issues: `project = {{project_key}} AND updated >= '{{timestamp}}' AND issuetype = '{BUG_ISSUE_TYPE}'`.\n"
            f"   - Ensure you fetch enough issues (handling pagination if the tool requires it, or asking for max results).\n"
            f"4. For the found issues, analyze their status:\n"
            f"   - Valid statuses are: {VALID_STATUSES}\n"
            f"   - If the status is in the valid list, add it to the list for `upsert_issues`.\n"
            f"   - If the status is NOT in the valid list, add its key to the list for `delete_issues`.\n"
            f"5. Call `upsert_issues` with the valid issues and `delete_issues` with the invalid issue keys. Ensure you pass the correct `project_key`.\n"
            f"6. After successfully processing all issues, call `save_last_update_timestamp` with the `project_key` and current time (use formatted string like 'YYYY-MM-DD HH:mm').\n"
            f"7. Return a result summarizing the actions (processed count)."
        )

        super().__init__(
            agent_name=config.JiraRagUpdateAgentConfig.OWN_NAME,
            base_url=config.AGENT_BASE_URL,
            port=config.JiraRagUpdateAgentConfig.PORT,
            external_port=config.JiraRagUpdateAgentConfig.EXTERNAL_PORT,
            protocol=config.JiraRagUpdateAgentConfig.PROTOCOL,
            model_name=config.JiraRagUpdateAgentConfig.MODEL_NAME,
            output_type=RagUpdateResult,
            instructions=instruction_prompt,
            mcp_servers=[jira_mcp_server],
            description="Agent responsible for keeping the RAG Vector DB up-to-date with Jira issues.",
            tools=[self.get_last_update_timestamp, self.save_last_update_timestamp, self.upsert_issues, self.delete_issues]
        )

    def get_thinking_budget(self) -> int:
        return config.JiraRagUpdateAgentConfig.THINKING_BUDGET

    def get_max_requests_per_task(self) -> int:
        return config.JiraRagUpdateAgentConfig.MAX_REQUESTS_PER_TASK

    async def get_last_update_timestamp(self, project_key: str) -> str:
        """Retrieves the last update timestamp for the project from the metadata DB. 
        Returns '1970-01-01 00:00' if not found."""
        try:
            await self.metadata_db._ensure_collection()
            # Direct client access to retrieve by ID (project_key)
            points = await self.metadata_db.client.retrieve(
                collection_name=METADATA_COLLECTION,
                ids=[project_key]
            )
            if points and points[0].payload:
                return points[0].payload.get("last_update", "1970-01-01 00:00")
            return "1970-01-01 00:00"
        except Exception as e:
            logger.error(f"Error fetching last update: {e}")
            return "1970-01-01 00:00"

    async def save_last_update_timestamp(self, project_key: str, timestamp: str) -> str:
        """Saves the last update timestamp for the project."""
        try:
            await self.metadata_db.upsert(
                data=f"Metadata for {project_key}",
                metadata={"last_update": timestamp},
                point_id=project_key
            )
            return "Timestamp saved."
        except Exception as e:
            logger.error(f"Error saving last update: {e}")
            return f"Error saving timestamp: {e}"

    async def upsert_issues(self, project_key: str, issues: List[dict]) -> str:
        """Upserts a list of Jira issues into the vector DB. 
        Expects issues to have 'key', 'id', 'fields.summary', 'fields.description', 'fields.status.name', 'fields.issuetype.name'.
        """
        count = 0
        try:
            for issue in issues:
                key = issue.get("key")
                issue_id = str(issue.get("id", ""))
                fields = issue.get("fields", {})
                summary = fields.get("summary", "")
                description = fields.get("description", "") or ""
                
                status_obj = fields.get("status", {})
                status = status_obj.get("name") if isinstance(status_obj, dict) else str(status_obj)
                
                issuetype_obj = fields.get("issuetype", {})
                issue_type = issuetype_obj.get("name") if isinstance(issuetype_obj, dict) else str(issuetype_obj)
                
                jira_issue = JiraIssue(
                    id=issue_id,
                    key=key,
                    summary=summary,
                    description=description,
                    issue_type=issue_type
                )
                
                # Using issue key as point_id
                await self.issues_db.upsert(
                    data=jira_issue,
                    metadata={
                        "issue_key": key,
                        "project": project_key,
                        "status": status,
                        "source": "jira_sync"
                    },
                    point_id=key
                )
                count += 1
            return f"Upserted {count} issues."
        except Exception as e:
            logger.error(f"Error upserting issues: {e}")
            return f"Error upserting issues: {e}"

    async def delete_issues(self, issue_keys: List[str]) -> str:
        """Deletes a list of Jira issues from the vector DB."""
        try:
            if not issue_keys:
                return "No issues to delete."
            await self.issues_db.delete(issue_keys)
            return f"Deleted {len(issue_keys)} issues."
        except Exception as e:
            logger.error(f"Error deleting issues: {e}")
            return f"Error deleting issues: {e}"


agent = JiraRagUpdateAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()
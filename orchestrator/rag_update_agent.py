# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import MCPServerSSE

import config
from common import utils
from common.agent_base import VectorDbService
from common.custom_llm_wrapper import CustomLlmWrapper

logger = utils.get_logger("rag_update_agent")

# Configuration
JIRA_MCP_SERVER_URL = config.JIRA_MCP_SERVER_URL
MODEL_NAME = getattr(config.OrchestratorConfig, "MODEL_NAME", "google-gla:gemini-2.5-flash")
RAG_COLLECTION = getattr(config.QdrantConfig, "COLLECTION_NAME", "jira_issues")
METADATA_COLLECTION = getattr(config.QdrantConfig, "METADATA_COLLECTION_NAME", "rag_metadata")
VALID_STATUSES = getattr(config.QdrantConfig, "VALID_STATUSES", ["To Do", "In Progress", "Done"])
BUG_ISSUE_TYPE = getattr(config.QdrantConfig, "BUG_ISSUE_TYPE", "Bug")

jira_mcp_server = MCPServerSSE(url=JIRA_MCP_SERVER_URL, timeout=config.MCP_SERVER_TIMEOUT_SECONDS)

# Services
issues_db = VectorDbService(RAG_COLLECTION)
metadata_db = VectorDbService(METADATA_COLLECTION)


class RagUpdateDeps(BaseModel):
    project_key: str


class RagUpdateResult(BaseModel):
    status: str
    processed_count: int


async def get_last_update_timestamp(ctx: RunContext[RagUpdateDeps]) -> str:
    """Retrieves the last update timestamp for the project from the metadata DB. 
    Returns '1970-01-01 00:00' if not found."""
    try:
        await metadata_db._ensure_collection()
        # Direct client access to retrieve by ID (project_key)
        points = await metadata_db.client.retrieve(
            collection_name=METADATA_COLLECTION,
            ids=[ctx.deps.project_key]
        )
        if points and points[0].payload:
            return points[0].payload.get("last_update", "1970-01-01 00:00")
        return "1970-01-01 00:00"
    except Exception as e:
        logger.error(f"Error fetching last update: {e}")
        return "1970-01-01 00:00"


async def save_last_update_timestamp(ctx: RunContext[RagUpdateDeps], timestamp: str) -> str:
    """Saves the last update timestamp for the project."""
    try:
        await metadata_db.upsert(
            text=f"Metadata for {ctx.deps.project_key}",
            metadata={"last_update": timestamp},
            point_id=ctx.deps.project_key
        )
        return "Timestamp saved."
    except Exception as e:
        logger.error(f"Error saving last update: {e}")
        return f"Error saving timestamp: {e}"


async def upsert_issues(ctx: RunContext[RagUpdateDeps], issues: List[dict]) -> str:
    """Upserts a list of Jira issues into the vector DB. 
    Expects issues to have 'key', 'fields.summary', 'fields.description', 'fields.status.name'.
    """
    count = 0
    try:
        for issue in issues:
            key = issue.get("key")
            fields = issue.get("fields", {})
            summary = fields.get("summary", "")
            description = fields.get("description", "") or ""
            status_obj = fields.get("status", {})
            status = status_obj.get("name") if isinstance(status_obj, dict) else str(status_obj)
            
            content = f"Key: {key}\nSummary: {summary}\nDescription: {description}\nStatus: {status}"
            
            # Using issue key as point_id
            await issues_db.upsert(
                text=content,
                metadata={
                    "issue_key": key,
                    "project": ctx.deps.project_key,
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


async def delete_issues(ctx: RunContext[RagUpdateDeps], issue_keys: List[str]) -> str:
    """Deletes a list of Jira issues from the vector DB."""
    try:
        if not issue_keys:
            return "No issues to delete."
        await issues_db.delete(issue_keys)
        return f"Deleted {len(issue_keys)} issues."
    except Exception as e:
        logger.error(f"Error deleting issues: {e}")
        return f"Error deleting issues: {e}"


rag_update_agent = Agent(
    model=CustomLlmWrapper(wrapped=MODEL_NAME),
    output_type=RagUpdateResult,
    deps_type=RagUpdateDeps,
    mcp_servers=[jira_mcp_server],
    tools=[get_last_update_timestamp, save_last_update_timestamp, upsert_issues, delete_issues],
    system_prompt=(
        f"You are an agent responsible for keeping the RAG Vector DB up-to-date with Jira issues.\n"
        f"Your task is to sync bugs for a specific project.\n"
        f"1. Get the last update timestamp using `get_last_update_timestamp`.\n"
        f"2. Search Jira (using available MCP tools) for issues in the project that were CREATED or UPDATED after the timestamp.\n"
        f"   - Use JQL to find issues: `project = {{project_key}} AND updated >= '{{timestamp}}' AND issuetype = '{BUG_ISSUE_TYPE}'`.\n"
        f"   - Ensure you fetch enough issues (handling pagination if the tool requires it, or asking for max results).\n"
        f"3. For the found issues, analyze their status:\n"
        f"   - Valid statuses are: {VALID_STATUSES}\n"
        f"   - If the status is in the valid list, add it to the list for `upsert_issues`.\n"
        f"   - If the status is NOT in the valid list, add its key to the list for `delete_issues`.\n"
        f"4. Call `upsert_issues` with the valid issues and `delete_issues` with the invalid issue keys.\n"
        f"5. After successfully processing all issues, call `save_last_update_timestamp` with the current time (use formatted string like 'YYYY-MM-DD HH:mm').\n"
        f"6. Return a result summarizing the actions (processed count)."
    )
)

# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import base64
import json
import os
import time
import uuid

from a2a.types import FilePart, FileWithBytes
from pydantic_ai.mcp import MCPServerSSE
from pydantic_ai.settings import ThinkingLevel
from qdrant_client import models as qdrant_models

import config
from agents.incident_creation.prompt import DuplicateDetectionPrompt, IncidentCreationPrompt
from common import utils
from common.agent_base import AgentBase
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import (
    DuplicateCandidate,
    DuplicateDetectionResult,
    IncidentCreationInput,
    IncidentCreationResult,
    JiraIssue,
)
from common.services.test_management_system_client_provider import get_test_management_client

logger = utils.get_logger("incident_creation_agent")

# Qdrant RAG Config
QDRANT_COLLECTION_NAME = getattr(config.QdrantConfig, "TICKETS_COLLECTION_NAME", "jira_issues")
RAG_MIN_SIMILARITY = getattr(config.IncidentCreationAgentConfig, "MIN_SIMILARITY_SCORE", 0.7)
BUG_ISSUE_TYPE = getattr(config.QdrantConfig, "BUG_ISSUE_TYPE", "Bug")
TERMINAL_STATUSES = set(getattr(config.IncidentCreationAgentConfig, "TERMINAL_STATUSES", []))
JIRA_MCP_SERVER_URL = config.JIRA_MCP_SERVER_URL

jira_mcp_server = MCPServerSSE(url=JIRA_MCP_SERVER_URL, timeout=config.MCP_SERVER_TIMEOUT_SECONDS)


class IncidentCreationAgent(AgentBase):
    """Agent for creating incident reports in Jira.
    """

    def __init__(self):
        self.main_prompt = IncidentCreationPrompt()
        self.dup_detect_prompt = DuplicateDetectionPrompt()
        model_name = config.IncidentCreationAgentConfig.MODEL_NAME
        self.duplicate_detector = CustomLlmWrapper.create_agent(
            model_name=model_name,
            output_type=DuplicateDetectionResult,
            system_prompt=self.dup_detect_prompt.get_prompt(),
            name="duplicate_detector",
            thinking_level=config.IncidentCreationAgentConfig.THINKING_LEVEL
        )

        self._saved_artifact_paths: list[str] = []
        self._media_files: list[FileWithBytes] = []

        super().__init__(
            agent_name=config.IncidentCreationAgentConfig.OWN_NAME,
            base_url=config.AGENT_BASE_URL,
            protocol=config.IncidentCreationAgentConfig.PROTOCOL,
            port=config.IncidentCreationAgentConfig.PORT,
            external_port=config.IncidentCreationAgentConfig.EXTERNAL_PORT,
            model_name=model_name,
            output_type=IncidentCreationResult,
            instructions=self.main_prompt.get_prompt(),
            mcp_servers=[jira_mcp_server],
            deps_type=IncidentCreationInput,
            description="Agent which creates detailed incident reports in Jira based on test execution results.",
            tools=[self._search_duplicate_candidates_in_rag, self._get_linked_issues, self._check_all_duplicates, self._save_artifacts,
                   self._link_issue_to_test_case],
            vector_db_collection_name=QDRANT_COLLECTION_NAME
        )

    def get_thinking_level(self) -> ThinkingLevel:
        return config.IncidentCreationAgentConfig.THINKING_LEVEL

    def get_max_requests_per_task(self) -> int:
        return config.IncidentCreationAgentConfig.MAX_REQUESTS_PER_TASK

    async def _search_duplicate_candidates_in_rag(self, incident_description: str) -> list[JiraIssue]:
        """Searches for potential duplicate incidents using the RAG vector database.

        Args:
            incident_description: Description of the incident including the error description,
                                test case name, test step where the issue occurred, steps to reproduce, system info etc.

        Returns:
            List of JiraIssue objects representing potential duplicate incidents.
        """
        logger.info("Starting RAG duplicate candidate search...")
        if not self.vector_db_service:
            logger.warning("Vector DB service not initialized, skipping RAG search.")
            return []

        bug_filter = qdrant_models.Filter(
            must=[
                qdrant_models.FieldCondition(
                    key="issue_type",
                    match=qdrant_models.MatchValue(value=BUG_ISSUE_TYPE),
                )
            ],
            must_not=[
                qdrant_models.FieldCondition(
                    key="status",
                    match=qdrant_models.MatchAny(any=list(TERMINAL_STATUSES)),
                )
            ] if TERMINAL_STATUSES else [],
        )

        hits = await self.vector_db_service.search(
            incident_description,
            limit=config.QdrantConfig.MAX_RESULTS,
            score_threshold=RAG_MIN_SIMILARITY,
            query_filter=bug_filter,
        )

        candidates: list[JiraIssue] = []
        for hit in hits:
            if hit.payload:
                try:
                    issue = JiraIssue.model_validate(hit.payload)
                    if issue.status and issue.status in TERMINAL_STATUSES:
                        logger.info(f"Skipping RAG candidate {issue.key} with terminal status '{issue.status}'.")
                        continue
                    candidates.append(issue)
                except Exception as e:
                    logger.warning(f"Failed to parse JiraIssue from payload: {e}")

        logger.info(f"Found {len(candidates)} potential duplicates via RAG.")
        return candidates

    @staticmethod
    async def _get_linked_issues(test_case_key: str) -> list[str]:
        """Fetches all Jira issues linked to the test case.

        Args:
            test_case_key: The key of the test case (e.g., 'PROJ-T123').

        Returns:
            List of Jira issues linked to the test case.
        """
        try:
            test_management_client = get_test_management_client()
            linked_issues = test_management_client.fetch_linked_issues(test_case_key)
            return [json.dumps(linked_issue) for linked_issue in linked_issues]

        except Exception:
            logger.exception(f"Error fetching linked issues for test case {test_case_key}.")
            raise

    def _save_artifacts(self) -> list[str]:
        """Saves all received file artifacts into the file system and returns their paths.

        Files are saved to the local/host path (ATTACHMENTS_LOCAL_DESTINATION_FOLDER_PATH) but
        the returned paths use the MCP server's container path (MCP_SERVER_ATTACHMENTS_FOLDER_PATH)
        since the Jira MCP server runs in Docker and expects paths relative to its filesystem.
        """
        import posixpath

        saved_paths: list[str] = []
        # Local path where files are actually saved (e.g., /tmp in Linux or D:\\temp on Windows)
        local_folder = config.ATTACHMENTS_LOCAL_DESTINATION_FOLDER_PATH
        # MCP container path for the Jira MCP server (e.g., /tmp in Docker)
        mcp_folder = config.MCP_SERVER_ATTACHMENTS_FOLDER_PATH

        # Ensure the destination folder exists
        os.makedirs(local_folder, exist_ok=True)

        total_parts = len(self.latest_received_message.parts)
        logger.info(f"Saving artifacts: scanning {total_parts} message part(s).")
        for part in self.latest_received_message.parts:
            if isinstance(part.root, FilePart):
                file_part = part.root
                if isinstance(file_part.file, FileWithBytes):
                    try:
                        file = file_part.file
                        file_content = base64.b64decode(file.bytes)
                        unique_id = str(uuid.uuid4())[:8]
                        original_name = file.name or "attachment"
                        safe_filename = f"{unique_id}_{original_name}"
                        # Save to the local/host filesystem
                        local_file_path = os.path.join(local_folder, safe_filename)
                        with open(local_file_path, 'wb') as f:
                            f.write(file_content)
                        # Return the MCP container path (with forward slashes for Docker)
                        mcp_file_path = posixpath.join(mcp_folder, safe_filename)
                        saved_paths.append(mcp_file_path)
                        logger.info(f"Saved artifact '{original_name}' to {local_file_path} (MCP path: {mcp_file_path})")
                    except Exception:
                        logger.exception("Failed to save artifact.")

        if saved_paths:
            logger.info(f"Saved {len(saved_paths)} artifact(s) for MCP server.")
        else:
            logger.info("No file artifacts found in the received message parts.")
        return saved_paths

    async def _check_all_duplicates(
            self,
            input_data: IncidentCreationInput,
            candidates: list[DuplicateCandidate]) -> DuplicateDetectionResult:
        """Checks which candidate incidents are the duplicates of the current incident.

        Args:
            input_data: The incident info which contains all available details about the failure.
            candidates: All candidate incidents to check.

        Returns: A single duplicate detection result containing duplicate detection result.
        """
        if not candidates:
            return DuplicateDetectionResult(message="No duplicate candidates were provided.")

        unique_candidates: list[DuplicateCandidate] = []
        seen_keys: set[str] = set()
        for candidate in candidates:
            if candidate.key in seen_keys:
                continue
            seen_keys.add(candidate.key)
            unique_candidates.append(candidate)

        duplicate_count = len(candidates) - len(unique_candidates)
        if duplicate_count:
            logger.info(f"Removed {duplicate_count} candidate(s) because they are the instances of the same issue.")

        user_message = (
            "New incident:\n"
            f"```\n{input_data.model_dump_json(indent=2)}\n```\n\n"
            "Already reported incidents:\n"
            f"```\n{json.dumps([candidate.model_dump() for candidate in unique_candidates], indent=2)}\n```"
        )

        logger.info(f"Starting duplicate check for {len(unique_candidates)} candidate(s)...")
        start = time.monotonic()
        result = await self.duplicate_detector.run(user_message)
        logger.info(
            f"Duplicate check for {len(unique_candidates)} candidate(s) completed in {time.monotonic() - start:.3f}s"
        )
        return result.output

    @staticmethod
    async def _link_issue_to_test_case(test_case_key: str, issue_id: int, link_type: str) -> str:
        """Links a bug issue to the test case using the test management system.

        Args:
            test_case_key: The key of the test case (e.g., 'PROJ-T123').
            issue_id: The numeric ID of the created bug issue (not the key, but the ID).
            link_type: The type of link (e.g., 'Blocks', 'Relates').

        Returns:
            A confirmation message indicating success or failure.
        """
        try:
            test_management_client = get_test_management_client()
            test_management_client.link_issue_to_test_case(test_case_key, issue_id, link_type)
            return f"Successfully linked issue {issue_id} to test case {test_case_key} with type {link_type}"
        except Exception:
            logger.exception(f"Error linking issue {issue_id} to test case {test_case_key}.")
            raise


agent = IncidentCreationAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()

# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import base64
import json
import os
import uuid
from typing import List

from a2a.types import FilePart, FileWithBytes
from pydantic_ai import Agent
from qdrant_client import models as qdrant_models
from pydantic_ai.mcp import MCPServerSSE

import config
from agents.incident_creation.prompt import IncidentCreationPrompt, DuplicateDetectionPrompt
from common import utils
from common.agent_base import AgentBase
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import (
    IncidentCreationInput,
    IncidentCreationResult,
    DuplicateDetectionResult,
)
from common.services.test_management_system_client_provider import get_test_management_client

logger = utils.get_logger("incident_creation_agent")

# Qdrant RAG Config
QDRANT_COLLECTION_NAME = getattr(config.QdrantConfig, "TICKETS_COLLECTION_NAME", "jira_issues")
RAG_MIN_SIMILARITY = getattr(config.IncidentCreationAgentConfig, "MIN_SIMILARITY_SCORE", 0.7)
BUG_ISSUE_TYPE = getattr(config.QdrantConfig, "BUG_ISSUE_TYPE", "Bug")
JIRA_MCP_SERVER_URL = config.JIRA_MCP_SERVER_URL

jira_mcp_server = MCPServerSSE(url=JIRA_MCP_SERVER_URL, timeout=config.MCP_SERVER_TIMEOUT_SECONDS)


class IncidentCreationAgent(AgentBase):
    """Agent for creating incident reports in Jira.
    """

    def __init__(self):
        self.main_prompt = IncidentCreationPrompt()
        self.dup_detect_prompt = DuplicateDetectionPrompt()

        model_name = getattr(config, "IncidentCreationAgentConfig", config.TestCaseGenerationAgentConfig).MODEL_NAME

        self.duplicate_detector = Agent(
            model=CustomLlmWrapper(wrapped=model_name),
            output_type=DuplicateDetectionResult,
            system_prompt=self.dup_detect_prompt.get_prompt(),
            name="duplicate_detector",
        )

        agent_config = getattr(config, "IncidentCreationAgentConfig", None)
        port = agent_config.PORT if agent_config else 8005
        ext_port = agent_config.EXTERNAL_PORT if agent_config else 8005
        own_name = agent_config.OWN_NAME if agent_config else "Incident Creation Agent"
        thinking_budget = agent_config.THINKING_BUDGET if agent_config else 16000
        self._thinking_budget = thinking_budget
        self._saved_artifact_paths: list[str] = []
        self._media_files: list[FileWithBytes] = []

        super().__init__(
            agent_name=own_name,
            base_url=config.AGENT_BASE_URL,
            protocol="http",
            port=port,
            external_port=ext_port,
            model_name=model_name,
            output_type=IncidentCreationResult,
            instructions=self.main_prompt.get_prompt(),
            mcp_servers=[jira_mcp_server],
            deps_type=IncidentCreationInput,
            description="Agent which creates detailed incident reports in Jira based on test execution results.",
            tools=[self._search_duplicate_candidates_in_rag, self._get_linked_issues, self._check_if_duplicate, self._save_artifacts, self._link_issue_to_test_case],
            vector_db_collection_name=QDRANT_COLLECTION_NAME
        )

    def get_thinking_budget(self) -> int:
        return self._thinking_budget

    def get_max_requests_per_task(self) -> int:
        return 10

    async def _search_duplicate_candidates_in_rag(self, incident_description: str) -> List[dict]:
        """Searches for potential duplicate incidents using the RAG vector database.
        
        This tool searches the vector database for semantically similar incidents based on the incident description.
        
        Args:
            incident_description: Description of the incident including the error description, 
                                test case name, test step where the issue occurred, steps to reproduce, system info etc.

        Returns:
            List of dicts with 'issue_key' and 'content' for each potential duplicate.
        """
        if not self.vector_db_service:
            logger.warning("Vector DB service not initialized, skipping RAG search.")
            return []

        bug_filter = qdrant_models.Filter(
            must=[
                qdrant_models.FieldCondition(
                    key="issue_type",
                    match=qdrant_models.MatchValue(value=BUG_ISSUE_TYPE),
                )
            ]
        )

        hits = await self.vector_db_service.search(
            incident_description,
            limit=config.QdrantConfig.MAX_RESULTS,
            score_threshold=RAG_MIN_SIMILARITY,
            query_filter=bug_filter,
        )

        candidates = [
            {
                "issue_key": hit.payload.get('issue_key', 'Unknown'),
                "content": hit.payload.get('content', ''),
                "similarity_score": hit.score
            }
            for hit in hits if hit.payload
        ]

        logger.info(f"Found {len(candidates)} potential duplicates via RAG.")
        return candidates

    @staticmethod
    async def _get_linked_issues(test_case_key: str) -> List[str]:
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

        except Exception as e:
            logger.error(f"Error fetching linked issues for test case {test_case_key}: {e}")
            return []

    def _save_artifacts(self) -> list[str]:
        """Saves all received file artifacts into the file system and returns their paths.
        """
        saved_paths: list[str] = []
        mcp_folder = config.MCP_SERVER_ATTACHMENTS_FOLDER_PATH
        for part in self.latest_received_message.parts:
            if isinstance(part, FilePart):
                file = part.file
                if isinstance(file, FileWithBytes):
                    try:
                        file_content = base64.b64decode(file.bytes)
                        unique_id = str(uuid.uuid4())[:8]
                        original_name = file.name or "attachment"
                        safe_filename = f"{unique_id}_{original_name}"
                        file_path = os.path.join(mcp_folder, safe_filename)
                        with open(file_path, 'wb') as f:
                            f.write(file_content)
                        saved_paths.append(file_path)
                        logger.info(f"Saved artifact '{original_name}' to {file_path}")
                    except Exception as e:
                        logger.error(f"Failed to save artifact: {e}")

        if saved_paths:
            logger.info(f"Saved {len(saved_paths)} artifacts")
        return saved_paths

    async def _check_if_duplicate(self, input_data: IncidentCreationInput, candidate_key: str,
                                  candidate_content: str) -> DuplicateDetectionResult:
        """Checks if a candidate issue is a duplicate of the current incident.

        Args:
            input_data: The incident info which contains all available details about the failure.
            candidate_key: The Jira issue key of the candidate duplicate (e.g., 'PROJ-123').
            candidate_content: The full content/description of the candidate issue to compare against.

        Returns: duplicate detection result.
        """
        prompt = (f"Current Incident:\n{input_data.model_dump_json()}\n\n"
                  f"Candidate Incident ({candidate_key}):\n{candidate_content}")
        result = await self.duplicate_detector.run(prompt)
        return result.output

    @staticmethod
    async def _link_issue_to_test_case(test_case_key: str, issue_id: int) -> str:
        """Links a bug issue to the test case using the test management system.
        
        Args:
            test_case_key: The key of the test case (e.g., 'PROJ-T123').
            issue_id: The numeric ID of the created bug issue (not the key, but the ID).

        Returns:
            A confirmation message indicating success or failure.
        """
        try:
            test_management_client = get_test_management_client()
            test_management_client.link_issue_to_test_case(test_case_key, issue_id)
            return f"Successfully linked issue {issue_id} to test case {test_case_key}"
        except Exception as e:
            logger.error(f"Error linking issue {issue_id} to test case {test_case_key}: {e}")
            return f"Failed to link issue {issue_id} to test case {test_case_key}: {str(e)}"


agent = IncidentCreationAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()

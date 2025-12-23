# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import os
import uuid
from typing import List
from pydantic_ai import Agent, RunContext
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

logger = utils.get_logger("incident_creation_agent")

# Qdrant RAG Config
QDRANT_COLLECTION_NAME = getattr(config.IncidentCreationAgentConfig, "COLLECTION_NAME", "incident_issues")
RAG_MIN_SIMILARITY = getattr(config.IncidentCreationAgentConfig, "MIN_SIMILARITY_SCORE", 0.7)
JIRA_MCP_SERVER_URL = config.JIRA_MCP_SERVER_URL

jira_mcp_server = MCPServerSSE(url=JIRA_MCP_SERVER_URL, timeout=config.MCP_SERVER_TIMEOUT_SECONDS)


class IncidentCreationAgent(AgentBase):
    """Agent for creating incident reports in Jira.
    
    This agent uses the Jira MCP Server for all Jira operations
    
    Custom tools:
    - search_duplicates_in_rag: Search for similar incidents in the RAG vector database
    - save_artifacts_for_mcp_upload: Save artifacts to filesystem for MCP upload
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
        tools = [self.search_duplicates_in_rag, self.save_artifacts_for_mcp_upload]
        agent_config = getattr(config, "IncidentCreationAgentConfig", None)
        port = agent_config.PORT if agent_config else 8005
        ext_port = agent_config.EXTERNAL_PORT if agent_config else 8005
        own_name = agent_config.OWN_NAME if agent_config else "Incident Creation Agent"
        thinking_budget = agent_config.THINKING_BUDGET if agent_config else 16000
        self._thinking_budget = thinking_budget

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
            tools=tools,
            vector_db_collection_name=QDRANT_COLLECTION_NAME
        )

    def get_thinking_budget(self) -> int:
        return self._thinking_budget

    def get_max_requests_per_task(self) -> int:
        return 10

    async def search_duplicates_in_rag(self, ctx: RunContext[IncidentCreationInput]) -> List[dict]:
        """Searches for potential duplicate incidents using the RAG vector database.
        
        This tool searches the vector database for semantically similar incidents based on the current failure description.

        Returns:
            List of dicts with 'issue_key' and 'content' for each potential duplicate.
        """
        input_data = ctx.deps
        failure_description = f"{input_data.test_execution_result}\n{input_data.system_description}"
        if input_data.agent_execution_logs:
            failure_description += f"\nLogs: {input_data.agent_execution_logs[:500]}..."

        if not self.vector_db_service:
            logger.warning("Vector DB service not initialized, skipping RAG search.")
            return []

        hits = await self.vector_db_service.search(
            failure_description,
            limit=config.QdrantConfig.MAX_RESULTS,
            score_threshold=RAG_MIN_SIMILARITY
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

    async def save_artifacts_for_mcp_upload(self, ctx: RunContext[IncidentCreationInput]) -> dict:
        """Saves available artifacts to the MCP server's filesystem for upload via MCP tools.
        
        This tool writes the in-memory artifacts (screenshots, logs) to the shared
        filesystem that the MCP server can access. After calling this tool, use
        the jira_update_issue MCP tool with the 'attachments' parameter to upload
        the files to the incident.
        
        Example usage after this tool returns:
        1. Call this tool to get the list of file paths
        2. Call jira_update_issue with:
           - issue_key: the incident key
           - attachments: comma-separated list of file paths returned by this tool
        
        Returns:
            A dict with:
            - 'file_paths': List of file paths on the MCP server filesystem
            - 'message': Status message
        """
        if not ctx.deps.available_artefacts:
            return {"file_paths": [], "message": "No artifacts to save."}

        saved_paths = []
        mcp_folder = config.MCP_SERVER_ATTACHMENTS_FOLDER_PATH

        for artifact in ctx.deps.available_artefacts:
            try:
                # Generate unique filename to avoid conflicts
                unique_id = str(uuid.uuid4())[:8]
                safe_filename = f"{unique_id}_{artifact.file_name}"
                file_path = os.path.join(mcp_folder, safe_filename)

                # Write the file to the MCP server's accessible filesystem
                with open(file_path, 'wb') as f:
                    # artifact.file can be bytes or a file-like object
                    if isinstance(artifact.file, bytes):
                        f.write(artifact.file)
                    else:
                        f.write(artifact.file.read())

                saved_paths.append(file_path)
                logger.info(f"Saved artifact {artifact.file_name} to {file_path}")
            except Exception as e:
                logger.error(f"Failed to save {artifact.file_name}: {e}")

        return {
            "file_paths": saved_paths,
            "message": f"Saved {len(saved_paths)} artifacts to MCP server filesystem. "
                       f"Use jira_update_issue with attachments='{','.join(saved_paths)}' to upload them."
        }

    async def _check_duplicate(self, input_data: IncidentCreationInput, candidate_key: str,
                               candidate_content: str) -> DuplicateDetectionResult:
        """Internal method to check if a candidate issue is a duplicate of the current incident."""
        prompt = f"Current Incident:\n{input_data.model_dump_json()}\n\nCandidate Incident ({candidate_key}):\n{candidate_content}"
        result = await self.duplicate_detector.run(prompt)
        return result.data


agent = IncidentCreationAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()

# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import base64
import os
import uuid
from typing import List

from a2a.types import Message, FilePart, FileWithBytes
from a2a.utils import get_message_text
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
    
    This agent uses the Jira MCP Server for all Jira operations.
    
    File attachments from incoming messages are automatically extracted and saved
    to the MCP server filesystem. The saved file paths are then provided as part
    of the agent input, allowing the agent to reference these files when creating
    incidents and uploading attachments via MCP tools.
    
    Custom tools:
    - search_duplicates_in_rag: Search for similar incidents in the RAG vector database
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
            tools=[self.search_duplicates_in_rag],
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

    @staticmethod
    def _extract_and_save_files_from_message(received_message: Message) -> list[str]:
        """Extracts file attachments from received message and saves them to the MCP server filesystem.
        
        This method directly extracts any FilePart attachments from the A2A message
        and saves them to the shared filesystem that the MCP server can access.
        
        Args:
            received_message: The A2A Message object containing potential file attachments.
        
        Returns:
            List of file paths where the attachments were saved on the MCP server filesystem.
        """
        saved_paths: list[str] = []
        mcp_folder = config.MCP_SERVER_ATTACHMENTS_FOLDER_PATH
        
        for part in received_message.parts:
            if isinstance(part, FilePart):
                file = part.file
                if isinstance(file, FileWithBytes):
                    try:
                        # Decode the base64 content
                        file_content = base64.b64decode(file.bytes)
                        
                        # Generate unique filename to avoid conflicts
                        unique_id = str(uuid.uuid4())[:8]
                        original_name = file.name or "attachment"
                        safe_filename = f"{unique_id}_{original_name}"
                        file_path = os.path.join(mcp_folder, safe_filename)
                        
                        # Write the file to the MCP server's accessible filesystem
                        with open(file_path, 'wb') as f:
                            f.write(file_content)
                        
                        saved_paths.append(file_path)
                        logger.info(f"Saved attachment '{original_name}' to {file_path}")
                    except Exception as e:
                        logger.error(f"Failed to save attachment from message: {e}")
        
        if saved_paths:
            logger.info(f"Extracted and saved {len(saved_paths)} attachments from received message.")
        else:
            logger.info("No file attachments found in received message.")
        
        return saved_paths
    
    async def run(self, received_message: Message) -> Message:
        """Overrides base run method to extract files from message and include paths in agent input.
        
        This method extracts any file attachments from the received message, saves them to
        the MCP server filesystem, and includes the saved file paths in the text input
        provided to the agent. This allows the agent to reference the files when creating
        incidents and uploading attachments via MCP tools.
        """
        # Extract and save file attachments from the message
        saved_file_paths = self._extract_and_save_files_from_message(received_message)
        
        # Get the text content from the message
        text_content = get_message_text(received_message)
        
        # Append saved file paths information to the input if files were saved
        if saved_file_paths:
            attachments_info = (
                f"\n\n---\nSAVED ATTACHMENT FILE PATHS (use these with jira_update_issue 'attachments' parameter):\n"
                f"{', '.join(saved_file_paths)}"
            )
            text_content += attachments_info
        
        logger.info("Got a task to execute, starting execution.")
        
        # Call the agent with just the text content (including file path info)
        result = await self._get_agent_execution_result([text_content])
        
        logger.info("Completed execution of the task.")
        return self._get_text_message_from_results(result)

    async def _check_duplicate(self, input_data: IncidentCreationInput, candidate_key: str,
                               candidate_content: str) -> DuplicateDetectionResult:
        """Internal method to check if a candidate issue is a duplicate of the current incident."""
        prompt = (f"Current Incident:\n{input_data.model_dump_json()}\n\n"
                  f"Candidate Incident ({candidate_key}):\n{candidate_content}")
        result = await self.duplicate_detector.run(prompt)
        return result.output


agent = IncidentCreationAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()

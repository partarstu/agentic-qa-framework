# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import base64
import os
import uuid
from pathlib import Path
from typing import List

from a2a.types import Message, FilePart, FileWithBytes, TextPart
from pydantic_ai import Agent
from pydantic_ai.messages import UserContent, BinaryContent, ImageMediaType, VideoMediaType
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
    
    The orchestrator passes all file artifacts as file parts in the A2A message.
    This agent:
    - Extracts and saves all artifacts to the MCP server filesystem 
    - Adds file paths to the user message text
    - Passes media files (images, videos) as BinaryContent for LLM visual analysis
    
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

    async def search_duplicates_in_rag(self, incident_description: str) -> List[dict]:
        """Searches for potential duplicate incidents using the RAG vector database.
        
        This tool searches the vector database for semantically similar incidents based on the incident description.
        
        Args:
            incident_description: Description of the incident including the error description, 
                                test case name, and test step where the issue occurred.

        Returns:
            List of dicts with 'issue_key' and 'content' for each potential duplicate.
        """
        if not self.vector_db_service:
            logger.warning("Vector DB service not initialized, skipping RAG search.")
            return []

        hits = await self.vector_db_service.search(
            incident_description,
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
    def _is_media_file(file: FileWithBytes) -> bool:
        """Check if a file is a media file (image or video)."""
        if not file.name:
            return False
        
        media_extensions = {
            # Images
            '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg', '.ico',
            # Videos
            '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mkv'
        }
        
        file_ext = Path(file.name).suffix.lower()
        return file_ext in media_extensions
    
    def _extract_and_save_artifacts(self, received_message: Message) -> tuple[list[str], list[FileWithBytes]]:
        """Extract artifacts from message, save them, and separate media files.
        
        Args:
            received_message: The A2A Message containing file parts.
            
        Returns:
            Tuple of (saved_file_paths, media_files_for_llm)
        """
        saved_paths: list[str] = []
        media_files: list[FileWithBytes] = []
        mcp_folder = config.MCP_SERVER_ATTACHMENTS_FOLDER_PATH
        
        for part in received_message.parts:
            if isinstance(part, FilePart):
                file = part.file
                if isinstance(file, FileWithBytes):
                    try:
                        # Decode and save the file
                        file_content = base64.b64decode(file.bytes)
                        
                        # Generate unique filename
                        unique_id = str(uuid.uuid4())[:8]
                        original_name = file.name or "attachment"
                        safe_filename = f"{unique_id}_{original_name}"
                        file_path = os.path.join(mcp_folder, safe_filename)
                        
                        # Write to MCP server filesystem
                        with open(file_path, 'wb') as f:
                            f.write(file_content)
                        
                        saved_paths.append(file_path)
                        logger.info(f"Saved artifact '{original_name}' to {file_path}")
                        
                        # Keep media files for LLM analysis
                        if self._is_media_file(file):
                            media_files.append(file)
                            
                    except Exception as e:
                        logger.error(f"Failed to save artifact: {e}")
        
        if saved_paths:
            logger.info(f"Saved {len(saved_paths)} artifacts, {len(media_files)} are media files for LLM")
        
        return saved_paths, media_files
    
    async def run(self, received_message: Message) -> Message:
        """Overrides base run method to handle artifact extraction and processing.
        """
        logger.info("Got a task to execute, starting execution.")
        
        # Extract and save all artifacts from the message
        saved_paths, media_files = self._extract_and_save_artifacts(received_message)
        
        # Get the JSON text content from themessage
        text_content = ""
        for part in received_message.parts:
            if isinstance(part, TextPart):
                text_content = part.text
                break
        
        # Add saved file paths information to the text
        if saved_paths:
            paths_info = (
                f"\n\n---\nSAVED ARTIFACT FILE PATHS (use these with jira MCP tools for attachments):\n"
                f"{chr(10).join(saved_paths)}"
            )
            text_content += paths_info
        
        # Build user content list: text + media files as BinaryContent
        user_content: List[UserContent] = [text_content]
        
        # Add media files for LLM analysis
        for media_file in media_files:
            file_content = base64.b64decode(media_file.bytes)
            mime_type = media_file.mimeType or ""
            
            if mime_type.startswith("image"):
                user_content.append(BinaryContent(data=file_content, media_type=ImageMediaType))
            elif mime_type.startswith("video"):
                user_content.append(BinaryContent(data=file_content, media_type=VideoMediaType))
        
        # Call the agent with the prepared content
        result = await self._get_agent_execution_result(user_content)
        
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

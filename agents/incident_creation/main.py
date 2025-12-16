# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import os
from typing import List, Optional

import asyncpg
from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import MCPServerSSE

import config
from agents.incident_creation.prompt import IncidentCreationPrompt, DuplicateDetectionPrompt
from common import utils
from common.agent_base import AgentBase
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models (
    IncidentCreationInput,
    IncidentCreationResult,
    DuplicateDetectionResult,
)

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

logger = utils.get_logger("incident_creation_agent")

# Placeholder for RAG config if not in config.py yet
RAG_POSTGRES_DSN = getattr(config, "RAG_POSTGRES_DSN", os.environ.get("RAG_POSTGRES_DSN", "postgresql://postgres:postgres@postgres:5432/rag_db"))
RAG_TABLE_NAME = getattr(config, "RAG_TABLE_NAME", os.environ.get("RAG_TABLE_NAME", "jira_issues_embeddings"))
RAG_MIN_SIMILARITY = getattr(config, "RAG_MIN_SIMILARITY", float(os.environ.get("RAG_MIN_SIMILARITY", "0.7")))
JIRA_MCP_SERVER_URL = config.JIRA_MCP_SERVER_URL

jira_mcp_server = MCPServerSSE(url=JIRA_MCP_SERVER_URL, timeout=config.MCP_SERVER_TIMEOUT_SECONDS)


class IncidentCreationAgent(AgentBase):
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
        
        # Tools available to the main agent
        tools = [self.find_and_analyze_duplicates]

        agent_config = getattr(config, "IncidentCreationAgentConfig", None)
        port = agent_config.PORT if agent_config else 8005
        ext_port = agent_config.EXTERNAL_PORT if agent_config else 8005
        own_name = agent_config.OWN_NAME if agent_config else "Incident Creation Agent"
        thinking_budget = agent_config.THINKING_BUDGET if agent_config else 16000

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
        )
        self._thinking_budget = thinking_budget
        
        # Initialize Google GenAI if API key is available
        if GENAI_AVAILABLE and os.environ.get("GOOGLE_API_KEY"):
            genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))

    def get_thinking_budget(self) -> int:
        return self._thinking_budget

    def get_max_requests_per_task(self) -> int:
        return 10

    async def find_and_analyze_duplicates(self, ctx: RunContext[IncidentCreationInput]) -> List[DuplicateDetectionResult]:
        """
        Searches for potential duplicate incidents using RAG and analyzes them.
        Returns a list of confirmed duplicates.
        """
        input_data = ctx.deps
        failure_description = f"{input_data.test_execution_result}\n{input_data.system_description}"
        if input_data.agent_execution_logs:
            failure_description += f"\nLogs: {input_data.agent_execution_logs[:500]}..."

        candidates = await self._search_duplicates(failure_description)
        logger.info(f"Found {len(candidates)} potential duplicates via RAG.")
        
        duplicates = []
        for candidate_key, candidate_content in candidates:
            is_dup_result = await self._check_duplicate(input_data, candidate_key, candidate_content)
            if is_dup_result.is_duplicate:
                duplicates.append(is_dup_result)
        
        return duplicates

    async def _search_duplicates(self, query_text: str) -> List[tuple[str, str]]:
        embedding = self._get_embedding(query_text)
        if not embedding:
            logger.warning("Could not generate embedding, skipping RAG search.")
            return []

        try:
            conn = await asyncpg.connect(RAG_POSTGRES_DSN)
            try:
                embedding_str = str(embedding)
                query = f"""
                    SELECT issue_key, content
                    FROM {RAG_TABLE_NAME}
                    WHERE 1 - (embedding <=> $1) > $2
                    ORDER BY embedding <=> $1
                    LIMIT 5
                """
                rows = await conn.fetch(query, embedding_str, RAG_MIN_SIMILARITY)
                return [(r['issue_key'], r['content']) for r in rows]
            finally:
                await conn.close()
        except Exception as e:
            logger.error(f"Error querying RAG database: {e}")
            return []

    async def _check_duplicate(self, input_data: IncidentCreationInput, candidate_key: str, candidate_content: str) -> DuplicateDetectionResult:
        prompt = f"Current Incident:\n{input_data.model_dump_json()}\n\nCandidate Incident ({candidate_key}):\n{candidate_content}"
        result = await self.duplicate_detector.run(prompt)
        return result.data

    def _get_embedding(self, text: str) -> Optional[List[float]]:
        if not GENAI_AVAILABLE:
            logger.warning("google-generativeai not installed.")
            return None
        
        try:
            model = "models/text-embedding-004"
            result = genai.embed_content(
                model=model,
                content=text,
                task_type="retrieval_query"
            )
            return result['embedding']
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return None

agent = IncidentCreationAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()

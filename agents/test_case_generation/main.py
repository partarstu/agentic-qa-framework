# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import re
from typing import List

from pydantic_ai import Agent
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.mcp import MCPServerSSE
from pydantic_ai.messages import UserContent
from pydantic_ai.usage import Usage

import config
from agents.test_case_generation.prompt import (
    TestCaseGenerationSystemPrompt,
    ACExtractionPrompt,
    StepsGenerationPrompt,
    TestCaseCreationPrompt,
)
from common import utils
from common.agent_base import AgentBase, MCP_SERVER_ATTACHMENTS_FOLDER_PATH
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import (
    JiraUserStory,
    GeneratedTestCases,
    StoryAndACs,
    TestStepsSequence,
    TestCase,
)
from common.services.test_management_system_client_provider import get_test_management_client

logger = utils.get_logger("test_case_generation_agent")
jira_mcp_server = MCPServerSSE(url=config.JIRA_MCP_SERVER_URL, timeout=config.MCP_SERVER_TIMEOUT_SECONDS)


class TestCaseGenerationAgent(AgentBase):
    def __init__(self):
        # Initialize sub-agent prompts
        self.ac_extraction_prompt = ACExtractionPrompt()
        self.steps_generation_prompt = StepsGenerationPrompt()
        self.test_case_creation_prompt = TestCaseCreationPrompt()

        # Initialize sub-agents
        model_name = config.TestCaseGenerationAgentConfig.MODEL_NAME

        self.ac_extractor_agent = Agent(
            model=CustomLlmWrapper(wrapped=model_name),
            output_type=StoryAndACs,
            system_prompt=self.ac_extraction_prompt.get_prompt(),
            mcp_servers=[jira_mcp_server],
            name="ac_extractor",
        )

        self.steps_generator_agent = Agent(
            model=CustomLlmWrapper(wrapped=model_name),
            output_type=TestStepsSequence,
            system_prompt=self.steps_generation_prompt.get_prompt(),
            name="steps_generator",
        )

        self.test_case_creator_agent = Agent(
            model=CustomLlmWrapper(wrapped=model_name),
            output_type=TestCase,
            system_prompt=self.test_case_creation_prompt.get_prompt(),
            name="test_case_creator",
        )

        # Initialize base agent (as orchestrator placeholder)
        # Note: We change output_type to str for the final confirmation message.
        instruction_prompt = TestCaseGenerationSystemPrompt(
            attachments_remote_folder_path=MCP_SERVER_ATTACHMENTS_FOLDER_PATH
        )
        super().__init__(
            agent_name=config.TestCaseGenerationAgentConfig.OWN_NAME,
            base_url=config.AGENT_BASE_URL,
            port=config.TestCaseGenerationAgentConfig.PORT,
            external_port=config.TestCaseGenerationAgentConfig.EXTERNAL_PORT,
            protocol=config.TestCaseGenerationAgentConfig.PROTOCOL,
            model_name=config.TestCaseGenerationAgentConfig.MODEL_NAME,
            output_type=str,
            instructions=instruction_prompt.get_prompt(),  # Kept for compatibility/fallback
            mcp_servers=[jira_mcp_server],
            deps_type=JiraUserStory,
            description="Agent which generates test cases based on Jira user stories.",
            tools=[self._create_test_cases],
        )

    def get_thinking_budget(self) -> int:
        return config.TestCaseGenerationAgentConfig.THINKING_BUDGET

    def get_max_requests_per_task(self) -> int:
        return config.TestCaseGenerationAgentConfig.MAX_REQUESTS_PER_TASK

    async def _get_agent_execution_result(self, received_request: List[UserContent]) -> AgentRunResult:
        """
        Orchestrates the multi-agent workflow.
        """
        logger.info("Starting multi-agent test case generation workflow.")

        # Extract issue key from the request (assuming it's text)
        request_text = ""
        for content in received_request:
            if isinstance(content, str):
                request_text += content + " "
        
        # Simple regex to find potential issue key like PROJ-123
        match = re.search(r"([A-Z][A-Z0-9]+-\d+)", request_text)
        issue_key = match.group(1) if match else request_text.strip()

        # 1 & 2. Fetch Story & Extract ACs (Combined)
        logger.info(f"Step 1 & 2: Fetching Story and Extracting ACs for key: {issue_key}")
        ac_result = await self.ac_extractor_agent.run(f"Jira Issue Key: {issue_key}")
        story_and_acs = ac_result.data
        story = story_and_acs.story
        acs = story_and_acs.acs
        
        logger.info(f"Fetched story: {story.key} (ID: {story.id})")
        logger.info(f"Extracted {len(acs.items)} ACs.")

        test_cases_list = []

        # 3 & 4. Generate Steps and Create Test Cases
        logger.info("Step 3 & 4: Generating Steps and Test Cases for each AC...")
        for ac in acs.items:
            logger.info(f"Processing AC: {ac.id}")
            
            # Step Generation
            steps_result = await self.steps_generator_agent.run(
                f"Acceptance Criterion: {ac.model_dump_json()}\nUser Story Context: {story.model_dump_json()}"
            )
            steps_seq = steps_result.data

            # Test Case Creation
            tc_result = await self.test_case_creator_agent.run(
                f"Steps: {steps_seq.model_dump_json()}\nAC: {ac.model_dump_json()}\nStory: {story.model_dump_json()}"
            )
            test_cases_list.append(tc_result.data)

        logger.info(f"Generated {len(test_cases_list)} test cases.")

        # 5. Finalize & Save
        generated_test_cases = GeneratedTestCases(test_cases=test_cases_list)
        
        # Extract project key from story key (e.g., "PROJ-123" -> "PROJ")
        project_key = story.key.split('-')[0]
        
        logger.info(f"Creating test cases in system for Project: {project_key}, Story ID: {story.id}")
        confirmation_msg = self._create_test_cases(generated_test_cases, project_key, story.id)
        
        return AgentRunResult(
            data=confirmation_msg,
            usage=Usage(), # Usage tracking not implemented for aggregate
            messages=[]
        )

    @staticmethod
    def _create_test_cases(test_cases: GeneratedTestCases, project_key: str, user_story_id: int) -> str:
        """
        Creates the generated test cases in the configured test management system.

        Args:
            test_cases: The list of test cases to be created.
            project_key: The key of the Jira project to which the Jira issue belongs.
            user_story_id: ID of the Jira user story (not its key), e.g. 120.

        Returns:
            A confirmation message with the keys (IDs) of the created test cases.
        """

        client = get_test_management_client()
        created_test_case_ids = client.create_test_cases(test_cases.test_cases, project_key, user_story_id)
        return f"Successfully created test cases with following keys (IDs): {', '.join(created_test_case_ids)}"


agent = TestCaseGenerationAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()

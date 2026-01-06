# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerSSE
from pydantic_ai.messages import BinaryContent

import config
from agents.test_case_generation.prompt import (
    TestCaseGenerationSystemPrompt,
    AcExtractionPrompt,
    StepsGenerationPrompt,
    TestCaseCreationPrompt,
)
from common import utils
from common.agent_base import AgentBase, MCP_SERVER_ATTACHMENTS_FOLDER_PATH
from common.custom_llm_wrapper import CustomLlmWrapper
from common.models import (
    JiraUserStory,
    GeneratedTestCases,
    AcceptanceCriteriaList, TestStepsSequenceList,
)
from common.services.test_management_system_client_provider import get_test_management_client

logger = utils.get_logger("test_case_generation_agent")
jira_mcp_server = MCPServerSSE(url=config.JIRA_MCP_SERVER_URL, timeout=config.MCP_SERVER_TIMEOUT_SECONDS)


class TestCaseGenerationAgent(AgentBase):
    __test__ = False

    def __init__(self):
        # Initialize sub-agent prompts
        self.ac_extraction_prompt = AcExtractionPrompt()
        self.steps_generation_prompt = StepsGenerationPrompt()
        self.test_case_creation_prompt = TestCaseCreationPrompt()

        # Initialize sub-agents
        model_name = config.TestCaseGenerationAgentConfig.MODEL_NAME

        self.ac_extractor_agent = Agent(
            model=CustomLlmWrapper(wrapped=model_name),
            output_type=AcceptanceCriteriaList,
            system_prompt=self.ac_extraction_prompt.get_prompt(),
            toolsets=[jira_mcp_server],
            name="ac_extractor",
        )

        self.steps_generator_agent = Agent(
            model=CustomLlmWrapper(wrapped=model_name),
            output_type=TestStepsSequenceList,
            system_prompt=self.steps_generation_prompt.get_prompt(),
            name="steps_generator",
        )

        self.test_case_creator_agent = Agent(
            model=CustomLlmWrapper(wrapped=model_name),
            output_type=GeneratedTestCases,
            system_prompt=self.test_case_creation_prompt.get_prompt(),
            name="test_case_creator",
        )

        # Initialize base agent (as orchestrator placeholder)
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
            output_type=GeneratedTestCases,
            instructions=instruction_prompt.get_prompt(),
            mcp_servers=[jira_mcp_server],
            deps_type=JiraUserStory,
            description="Agent which generates test cases based on Jira user stories.",
            tools=[self._upload_test_cases_into_test_management_system, self._generate_test_cases],
        )

    def get_thinking_budget(self) -> int:
        return config.TestCaseGenerationAgentConfig.THINKING_BUDGET

    def get_max_requests_per_task(self) -> int:
        return config.TestCaseGenerationAgentConfig.MAX_REQUESTS_PER_TASK

    async def _generate_test_cases(self, jira_issue_content: str, attachment_paths: list[str]) -> GeneratedTestCases:
        """
        Generates test cases based on the Jira issue content and attachments.

        Args:
            jira_issue_content: The whole content of the Jira issue.
            attachment_paths: List of file paths to the downloaded attachments.

        Returns:
            Generated test cases.
        """
        attachments_content = self._fetch_attachments(attachment_paths)
        extracted_acceptance_criteria = await self.extract_acceptance_criteria(attachments_content, jira_issue_content)
        test_steps_sequences = await self.generate_test_steps(extracted_acceptance_criteria)
        generated_test_cases = await self.create_test_cases_from_steps(extracted_acceptance_criteria, jira_issue_content,
                                                                       test_steps_sequences)
        return generated_test_cases

    async def create_test_cases_from_steps(self, extracted_acceptance_criteria: AcceptanceCriteriaList, jira_issue_content: str,
                                           test_steps_sequences: TestStepsSequenceList) -> GeneratedTestCases:
        logger.info("Generating Test Cases for all step sequences")
        user_message = f"""
Jira Issue content:
{jira_issue_content}


Acceptance Criteria Items:
{extracted_acceptance_criteria.model_dump_json()}


Test Step Sequences:
{test_steps_sequences.model_dump_json()}
"""
        result = await self.test_case_creator_agent.run(user_message)
        generated_test_cases: GeneratedTestCases = result.output
        logger.info(f"Generated {len(generated_test_cases.test_cases)} test cases.")
        return generated_test_cases

    async def generate_test_steps(self, extracted_acceptance_criteria: AcceptanceCriteriaList) -> TestStepsSequenceList:
        logger.info("Generating Steps for all ACs")
        user_message = f"Acceptance Criteria Items:\n{extracted_acceptance_criteria.model_dump_json()}"
        result = await self.steps_generator_agent.run(user_message)
        test_steps_sequences: TestStepsSequenceList = result.output
        logger.info(f"Generated {len(test_steps_sequences.items)} test step sequences with total "
                    f"of {sum(len(s.steps) for s in test_steps_sequences.items)} steps.")
        return test_steps_sequences

    async def extract_acceptance_criteria(self, attachments_content: dict[str, BinaryContent],
                                          jira_issue_content: str) -> AcceptanceCriteriaList:
        user_message_parts: list[str | BinaryContent] = [
            f"Jira Issue content:\n{jira_issue_content}"
        ]
        # Add attachment identifiers as context
        if attachments_content:                   
            for filename, binary_content in attachments_content.items():
                user_message_parts.append(f"Attachment: {filename}")
                user_message_parts.append(binary_content)

        logger.info("Starting AC extraction with %d attachments", len(attachments_content))
        result = await self.ac_extractor_agent.run(user_message_parts)
        extracted_acceptance_criteria: AcceptanceCriteriaList = result.output
        logger.info(f"Extracted {len(extracted_acceptance_criteria.items)} ACs")
        return extracted_acceptance_criteria

    @staticmethod
    def _upload_test_cases_into_test_management_system(test_cases: GeneratedTestCases, project_key: str,
                                                       user_story_id: int) -> str:
        """
        Uploads the provided test cases in the configured test management system.

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

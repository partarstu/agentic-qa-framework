# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from pydantic_ai.mcp import MCPServerSSE

import config
from common.agent_base import AgentBase, MCP_SERVER_ATTACHMENTS_FOLDER_PATH
from agents.test_case_generation.prompt import TestCaseGenerationSystemPrompt
from common import utils
from common.models import JiraUserStory, GeneratedTestCases
from common.services.test_management_system_client_provider import get_test_management_client

logger = utils.get_logger("test_case_generation_agent")
jira_mcp_server = MCPServerSSE(url=config.JIRA_MCP_SERVER_URL, timeout=config.MCP_SERVER_TIMEOUT_SECONDS)


class TestCaseGenerationAgent(AgentBase):
    def __init__(self):
        instruction_prompt = TestCaseGenerationSystemPrompt(
            attachments_remote_folder_path=MCP_SERVER_ATTACHMENTS_FOLDER_PATH)
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
            tools=[self._get_media_file_content, self._create_test_cases]
        )

    def get_thinking_budget(self) -> int:
        return config.TestCaseGenerationAgentConfig.THINKING_BUDGET

    def get_max_requests_per_task(self) -> int:
        return config.TestCaseGenerationAgentConfig.MAX_REQUESTS_PER_TASK

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

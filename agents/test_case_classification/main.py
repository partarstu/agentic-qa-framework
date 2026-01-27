# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from pydantic_ai.mcp import MCPServerSSE

import config
from agents.test_case_classification.prompt import TestCaseClassificationSystemPrompt
from common import utils
from common.agent_base import AgentBase
from common.models import ClassifiedTestCases, TestCaseKeys
from common.services.test_management_system_client_provider import get_test_management_client

logger = utils.get_logger("test_case_classification_agent")
jira_mcp_server = MCPServerSSE(url=config.JIRA_MCP_SERVER_URL, timeout=config.MCP_SERVER_TIMEOUT_SECONDS)


class TestCaseClassificationAgent(AgentBase):
    __test__ = False
    def __init__(self):
        instruction_prompt = TestCaseClassificationSystemPrompt()
        super().__init__(
            agent_name=config.TestCaseClassificationAgentConfig.OWN_NAME,
            base_url=config.AGENT_BASE_URL,
            port=config.TestCaseClassificationAgentConfig.PORT,
            external_port=config.TestCaseClassificationAgentConfig.EXTERNAL_PORT,
            protocol=config.TestCaseClassificationAgentConfig.PROTOCOL,
            model_name=config.TestCaseClassificationAgentConfig.MODEL_NAME,
            output_type=ClassifiedTestCases,
            instructions=instruction_prompt.get_prompt(),
            mcp_servers=[jira_mcp_server],
            deps_type=TestCaseKeys,
            description="Agent which classifies test cases based on their content",
            tools=[self.add_labels_to_test_case]
        )

    def get_thinking_budget(self) -> int:
        return config.TestCaseClassificationAgentConfig.THINKING_BUDGET

    def get_max_requests_per_task(self) -> int:
        return config.TestCaseClassificationAgentConfig.MAX_REQUESTS_PER_TASK

    @staticmethod
    def add_labels_to_test_case(test_case_key: str, labels: list[str]) -> str:
        """
        Adds labels to a test case.

        Args:
            test_case_key: The key or ID of the test case.
            labels: A list of labels to add.

        Returns:
            A confirmation message informing if the labels were successfully added.
        """
        client = get_test_management_client()
        client.add_labels_to_test_case(test_case_key, labels)
        return f"Successfully added labels {', '.join(labels)} to the test case with key(ID) '{test_case_key}'"


agent = TestCaseClassificationAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from pydantic_ai.settings import ThinkingLevel

import config
from agents.test_case_classification.prompt import TestCaseClassificationSystemPrompt
from common import utils
from common.agent_base import AgentBase
from common.models import AgentSkillDeclaration, ClassifiedTestCases, TestCaseKeys
from common.services.atlassian_mcp import build_atlassian_mcp_server_toolset
from common.services.test_management_system_client_provider import get_test_management_client

logger = utils.get_logger("test_case_classification_agent")

# The classification agent works purely on the test cases handed to it and labels them
# through the test management system, so it is filtered down to no Atlassian tools at
# all (WS11 per-agent tool filtering).
_JIRA_TOOL_ALLOWLIST: tuple[str, ...] = ()


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
            version=config.TestCaseClassificationAgentConfig.VERSION,
            max_output_tokens=config.TestCaseClassificationAgentConfig.MAX_OUTPUT_TOKENS,
            output_type=ClassifiedTestCases,
            instructions=instruction_prompt.get_prompt(),
            mcp_toolset_factories=[lambda: build_atlassian_mcp_server_toolset(_JIRA_TOOL_ALLOWLIST)],
            deps_type=TestCaseKeys,
            skill=AgentSkillDeclaration(
                id=config.TestCaseClassificationAgentConfig.SKILL_ID,
                name=config.TestCaseClassificationAgentConfig.SKILL_NAME,
                description=config.TestCaseClassificationAgentConfig.SKILL_DESCRIPTION,
            ),
            tools=[self.add_labels_to_test_case],
        )

    def get_thinking_level(self) -> ThinkingLevel:
        return config.TestCaseClassificationAgentConfig.THINKING_LEVEL

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

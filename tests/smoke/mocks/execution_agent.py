# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Mock A2A test-execution agent for the hermetic smoke suite.

Stands in for the (out-of-repo, VM-hosted) test-execution agents so the
``/execute-tests`` -> incident-creation path can run end to end without a real
test runner. It is a genuine A2A agent — discovered and dispatched to exactly
like the real ones — but instead of executing a test it returns a canned,
clearly *failed* execution report as text. The orchestrator's own results
extractor maps that text to a failed ``TestExecutionResult``, which in turn
drives incident creation. No LLM is called by this agent (``run`` is overridden).
"""

import os

from a2a.helpers import new_text_message
from a2a.types import Message
from pydantic import BaseModel
from pydantic_ai.settings import ThinkingLevel

import config
from common.agent_base import AgentBase

EXECUTION_AGENT_NAME = "Smoke API Test Executor"

_FAILED_EXECUTION_REPORT = """\
TEST EXECUTION REPORT
Overall status: FAILED

Step 1: Send POST /api/password-reset with a registered email address
  Expected: HTTP 200 and a password-reset email is queued
  Actual:   HTTP 500 Internal Server Error; no email was queued
  Error:    AssertionError: expected response status 200 but received 500

Environment: Smoke API Test Executor, ephemeral containerised test environment
"""


class _ExecutionOutput(BaseModel):
    """Unused output schema; this agent never invokes the model."""

    report: str


class MockExecutionAgent(AgentBase):
    """A2A agent that reports a fixed failed execution without calling any LLM."""

    def __init__(self):
        port = int(os.environ.get("PORT", "8001"))
        super().__init__(
            agent_name=EXECUTION_AGENT_NAME,
            base_url=config.AGENT_BASE_URL,
            protocol="http",
            port=port,
            external_port=int(os.environ.get("EXTERNAL_PORT", port)),
            model_name="google-gla:gemini-3.5-flash",
            output_type=_ExecutionOutput,
            instructions="Unused: this mock returns a fixed result without calling the model.",
            mcp_servers=[],
            description=(
                "Executes automated API and integration test cases against the system under test "
                "and reports detailed pass/fail execution results."
            ),
        )

    def get_thinking_level(self) -> ThinkingLevel:
        return "minimal"

    def get_max_requests_per_task(self) -> int:
        return 1

    async def run(self, received_message: Message) -> Message:
        self.latest_received_message = received_message
        return new_text_message(text=_FAILED_EXECUTION_REPORT)


agent = MockExecutionAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()

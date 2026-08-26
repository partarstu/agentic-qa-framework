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
from datetime import UTC, datetime, timedelta

from a2a.helpers import new_text_message
from a2a.types import Message
from pydantic import BaseModel
from pydantic_ai.settings import ThinkingLevel

import config
from common.agent_base import AgentBase

EXECUTION_AGENT_NAME = "Smoke API Test Executor"

# The report deliberately describes no environment of its own: the orchestrator only falls back to
# its own agent/version/environment description when the executor supplied none, and that fallback
# is what carries the execution traceability into the created incident.
_FAILED_EXECUTION_REPORT_TEMPLATE = """\
TEST EXECUTION REPORT
Overall status: FAILED
Execution started: {execution_started}
Execution ended: {execution_ended}

Step 1: Send POST /api/password-reset with a registered email address
  Started:  {step_started}
  Ended:    {step_ended}
  Expected: HTTP 200 and a password-reset email is queued
  Actual:   HTTP 500 Internal Server Error; no email was queued
  Error:    AssertionError: expected response status 200 but received 500
"""


def _as_utc_text(timestamp: datetime) -> str:
    return timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_failed_execution_report() -> str:
    """Builds the report around this run's UTC instant, so the smoke suite can assert that
    the dates reaching the test management system are UTC rather than a local time."""
    execution_ended = datetime.now(UTC)
    execution_started = execution_ended - timedelta(seconds=15)
    return _FAILED_EXECUTION_REPORT_TEMPLATE.format(
        execution_started=_as_utc_text(execution_started),
        execution_ended=_as_utc_text(execution_ended),
        step_started=_as_utc_text(execution_started + timedelta(seconds=5)),
        step_ended=_as_utc_text(execution_started + timedelta(seconds=13)),
    )


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
            version=os.environ.get("EXECUTION_AGENT_VERSION", "1.0"),
            output_type=_ExecutionOutput,
            instructions="Unused: this mock returns a fixed result without calling the model.",
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
        return new_text_message(text=_build_failed_execution_report())


agent = MockExecutionAgent()
app = agent.a2a_server

if __name__ == "__main__":
    agent.start_as_server()

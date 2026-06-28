# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Fixtures for the hermetic smoke suite.

The suite runs against the ``docker-compose.smoke.yml`` topology: a real
orchestrator and the four agents (driven by real Gemini), with the external
boundaries (Jira MCP, Jira REST, Zephyr) replaced by recording mocks. The
fixtures wait for the agents to register, then fire the two webhooks once each;
the test functions read the mocks' ``/__recorded`` endpoints and assert on what
reached each boundary.

URLs default to the published compose ports and are overridable via ``SMOKE_*``
env vars. The dashboard/API credentials are the fixed throwaway values baked into
``docker-compose.smoke.yml``.
"""

import os
import time

import httpx
import pytest

import config

ORCHESTRATOR_URL = os.environ.get("SMOKE_ORCHESTRATOR_URL", "http://localhost:8000").rstrip("/")
JIRA_REST_RECORDED_URL = os.environ.get("SMOKE_JIRA_REST_RECORDED_URL", "http://localhost:8080/__recorded")
JIRA_MCP_RECORDED_URL = os.environ.get("SMOKE_JIRA_MCP_RECORDED_URL", "http://localhost:9000/__recorded")
ZEPHYR_RECORDED_URL = os.environ.get("SMOKE_ZEPHYR_RECORDED_URL", "http://localhost:8090/__recorded")

# Fixed test credentials, matching docker-compose.smoke.yml.
ORCHESTRATOR_API_KEY = "smoke-api-key"
DASHBOARD_USERNAME = "smoke"
DASHBOARD_PASSWORD = "smoke-pass"

# The story seeded by the Jira MCP mock (jira_mcp_mock.SEEDED_ISSUE_KEY).
SEEDED_ISSUE_KEY = "SMOKE-1"
# The project the executable test case is seeded under (zephyr_mock + jira_mcp_mock).
SEEDED_PROJECT_KEY = "SMOKE"
# Name the mock executor registers under; must match mocks/execution_agent.EXECUTION_AGENT_NAME.
EXECUTION_AGENT_NAME = "Smoke API Test Executor"

# Canonical agent names the four agents register under; tracks config as the source of truth.
EXPECTED_AGENT_NAMES: set[str] = {
    config.RequirementsReviewAgentConfig.OWN_NAME,
    config.TestCaseGenerationAgentConfig.OWN_NAME,
    config.TestCaseClassificationAgentConfig.OWN_NAME,
    config.TestCaseReviewAgentConfig.OWN_NAME,
}
HEALTHY_AGENT_STATUSES = {"AVAILABLE", "BUSY"}

# The status the review flow moves a reviewed test case to; tracks config as the source of truth.
REVIEW_COMPLETE_STATUS = config.TestCaseReviewAgentConfig.REVIEW_COMPLETE_STATUS_NAME

# Agents the /execute-tests + incident-creation flow needs (beyond the core four).
EXECUTION_FLOW_AGENT_NAMES: set[str] = {EXECUTION_AGENT_NAME, config.IncidentCreationAgentConfig.OWN_NAME}

# The orchestrator startup + initial agent discovery can take a while to settle.
ORCHESTRATOR_READY_TIMEOUT = 120.0
AGENT_READY_TIMEOUT = 240.0
# A single webhook drives real LLM routing plus one or more full agent runs.
WEBHOOK_TIMEOUT = httpx.Timeout(1200.0)
POLL_INTERVAL = 5.0


@pytest.fixture(scope="session")
def http_client() -> httpx.Client:
    with httpx.Client(timeout=httpx.Timeout(60.0), follow_redirects=True) as client:
        yield client


@pytest.fixture(scope="session")
def auth_headers(http_client: httpx.Client) -> dict[str, str]:
    """Log in to the dashboard, retrying while the orchestrator is still starting."""
    deadline = time.monotonic() + ORCHESTRATOR_READY_TIMEOUT
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            response = http_client.post(
                f"{ORCHESTRATOR_URL}/api/auth/login",
                json={"username": DASHBOARD_USERNAME, "password": DASHBOARD_PASSWORD},
            )
            if response.status_code == 200:
                return {"Authorization": f"Bearer {response.json()['access_token']}"}
            last_error = f"{response.status_code} {response.text}"
        except httpx.TransportError as exc:
            last_error = str(exc)
        time.sleep(POLL_INTERVAL)
    pytest.fail(f"Orchestrator dashboard login did not succeed within {ORCHESTRATOR_READY_TIMEOUT}s: {last_error}")


@pytest.fixture(scope="session")
def webhook_headers() -> dict[str, str]:
    return {"X-API-Key": ORCHESTRATOR_API_KEY}


def _wait_for_agents_healthy(
    http_client: httpx.Client, auth_headers: dict[str, str], expected_names: set[str]
) -> None:
    """Wait until every expected agent is registered and healthy.

    Triggers a fresh discovery each cycle so the wait does not depend on the
    orchestrator's periodic discovery interval.
    """
    deadline = time.monotonic() + AGENT_READY_TIMEOUT
    registered: dict[str, str] = {}
    while time.monotonic() < deadline:
        http_client.post(f"{ORCHESTRATOR_URL}/api/dashboard/discovery", headers=auth_headers)
        response = http_client.get(f"{ORCHESTRATOR_URL}/api/dashboard/agents", headers=auth_headers)
        if response.status_code == 200:
            registered = {agent["name"]: agent["status"] for agent in response.json()}
            healthy = {name for name in expected_names if registered.get(name) in HEALTHY_AGENT_STATUSES}
            if healthy == expected_names:
                return
        time.sleep(POLL_INTERVAL)
    missing = expected_names - {n for n, s in registered.items() if s in HEALTHY_AGENT_STATUSES}
    pytest.fail(f"Agents not registered/healthy within {AGENT_READY_TIMEOUT}s. Missing: {missing}. Seen: {registered}")


@pytest.fixture(scope="session")
def agents_ready(http_client: httpx.Client, auth_headers: dict[str, str]) -> None:
    """Wait until all four core agents are registered and healthy."""
    _wait_for_agents_healthy(http_client, auth_headers, EXPECTED_AGENT_NAMES)


@pytest.fixture(scope="session")
def execution_stack_ready(http_client: httpx.Client, auth_headers: dict[str, str]) -> None:
    """Wait until the mock executor and the incident-creation agent are registered and healthy."""
    _wait_for_agents_healthy(http_client, auth_headers, EXECUTION_FLOW_AGENT_NAMES)


def _post_webhook(path: str, headers: dict[str, str]) -> httpx.Response:
    with httpx.Client(timeout=WEBHOOK_TIMEOUT, follow_redirects=True) as client:
        return client.post(f"{ORCHESTRATOR_URL}{path}", headers=headers, json={"issue_key": SEEDED_ISSUE_KEY})


@pytest.fixture(scope="session")
def requirements_review_response(agents_ready: None, webhook_headers: dict[str, str]) -> httpx.Response:
    """Fire the requirements-review webhook once and share the response."""
    return _post_webhook("/new-requirements-available", webhook_headers)


@pytest.fixture(scope="session")
def test_case_flow_response(agents_ready: None, webhook_headers: dict[str, str]) -> httpx.Response:
    """Fire the test-case generation/classification/review webhook once and share the response."""
    return _post_webhook("/story-ready-for-test-case-generation", webhook_headers)


@pytest.fixture(scope="session")
def execute_tests_response(execution_stack_ready: None, webhook_headers: dict[str, str]) -> httpx.Response:
    """Fire the /execute-tests webhook once for the seeded project and share the response."""
    with httpx.Client(timeout=WEBHOOK_TIMEOUT, follow_redirects=True) as client:
        return client.post(
            f"{ORCHESTRATOR_URL}/execute-tests", headers=webhook_headers, json={"project_key": SEEDED_PROJECT_KEY}
        )

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Fixtures for the hermetic smoke suite.

The suite runs against the ``docker-compose.smoke.yml`` topology: a real
orchestrator and the agents (driven by real Gemini), with the external
boundaries (Jira MCP, Jira REST, Zephyr, Qdrant + embedding) replaced by
recording mocks. The fixtures wait for all agents to register, then fire the
webhooks once, concurrently — the flows are mutually independent, so the
wall time is the longest flow instead of their sum. The test functions read the
mocks' ``/__recorded`` endpoints and assert on what reached each boundary.

URLs default to the published compose ports and are overridable via ``SMOKE_*``
env vars. The dashboard/API credentials are the fixed throwaway values baked into
``docker-compose.smoke.yml``.
"""

import os
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

import config
from tests.conftest import CONFIGURED_GOOGLE_API_KEY

ORCHESTRATOR_URL = os.environ.get("SMOKE_ORCHESTRATOR_URL", "http://localhost:8000").rstrip("/")
JIRA_REST_RECORDED_URL = os.environ.get("SMOKE_JIRA_REST_RECORDED_URL", "http://localhost:8080/__recorded")
JIRA_MCP_RECORDED_URL = os.environ.get("SMOKE_JIRA_MCP_RECORDED_URL", "http://localhost:9000/__recorded")
JIRA_MCP_SEEDED_STORY_URL = os.environ.get("SMOKE_JIRA_MCP_STORY_URL", "http://localhost:9000/__seeded_story")
ZEPHYR_RECORDED_URL = os.environ.get("SMOKE_ZEPHYR_RECORDED_URL", "http://localhost:8090/__recorded")
QDRANT_RECORDED_URL = os.environ.get("SMOKE_QDRANT_RECORDED_URL", "http://localhost:6333/__recorded")
CONFLUENCE_RECORDED_URL = os.environ.get("SMOKE_CONFLUENCE_RECORDED_URL", "http://localhost:8095/__recorded")
SHAREPOINT_RECORDED_URL = os.environ.get("SMOKE_SHAREPOINT_RECORDED_URL", "http://localhost:8097/__recorded")

# Fixed test credentials, matching docker-compose.smoke.yml.
ORCHESTRATOR_API_KEY = "smoke-api-key"
DASHBOARD_USERNAME = "smoke"
DASHBOARD_PASSWORD = "smoke-pass"

# The story seeded by the Jira MCP mock (jira_mcp_mock.SEEDED_ISSUE_KEY) and its numeric id.
SEEDED_ISSUE_KEY = "SMOKE-1"
SEEDED_ISSUE_ID = 10001
# The project the executable test case is seeded under (zephyr_mock + jira_mcp_mock).
SEEDED_PROJECT_KEY = "SMOKE"
# The ready-for-execution test case seeded by the Zephyr mock (zephyr_mock._EXECUTABLE_TC_KEY).
SEEDED_EXECUTABLE_TC_KEY = "SMOKE-T100"
# Its test-type label, one of the TestCaseType labels.
SEEDED_EXECUTABLE_TC_TYPE_LABEL = "api"
# The automated test case without a test-type label seeded by the Zephyr mock (zephyr_mock._UNTYPED_TC_KEY).
SEEDED_UNTYPED_TC_KEY = "SMOKE-T101"
# The issue in a formerly excluded status seeded by the Jira REST mock (jira_rest_mock._SEEDED_CLOSED_ISSUE).
SEEDED_CLOSED_ISSUE_KEY = "SMOKE-2"
# The compose file of the running stack, for the orchestrator restart check.
SMOKE_COMPOSE_FILE = os.environ.get(
    "SMOKE_COMPOSE_FILE", str(Path(__file__).resolve().parents[2] / "docker-compose.smoke.yml")
)
# The collection the RAG sync stores Jira issues in; tracks config as the source of truth.
TICKETS_COLLECTION_NAME = config.QdrantConfig.TICKETS_COLLECTION_NAME
# The collection the Confluence sync stores document parts in; tracks config.
DOCUMENTS_COLLECTION_NAME = config.DocumentRagConfig.DOCUMENTS_COLLECTION_NAME
# The Confluence space seeded by the Confluence REST mock (confluence_mock.SEEDED_SPACE_KEY).
SEEDED_SPACE_KEY = "SMOKEDOC"
# Name the mock executor registers under; must match mocks/execution_agent.EXECUTION_AGENT_NAME.
EXECUTION_AGENT_NAME = "Smoke API Test Executor"
# Version the mock executor is started with; must match EXECUTION_AGENT_VERSION in docker-compose.smoke.yml.
EXECUTION_AGENT_VERSION = "9.9-smoke"
# Version the orchestrator is started with; must match ORCHESTRATOR_VERSION in docker-compose.smoke.yml.
ORCHESTRATOR_VERSION = "8.8-smoke"
# Environment label the orchestrator reports every execution against; must match
# TEST_ENVIRONMENT_LABEL in docker-compose.smoke.yml.
TEST_ENVIRONMENT_LABEL = "Smoke Test Environment"

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
# The collection the test cases are indexed in; tracks config as the source of truth.
TEST_CASES_COLLECTION_NAME = config.QdrantConfig.TEST_CASES_COLLECTION_NAME
# Login attempts allowed per window; the smoke stack keeps the default.
LOGIN_RATE_LIMIT_ATTEMPTS = config.DashboardAuthConfig.LOGIN_RATE_LIMIT_ATTEMPTS
# Heading of the duplicate-check section of a review comment; must match
# agents.test_case_review.main.DUPLICATE_CHECK_HEADING (not imported: importing it starts the agent).
DUPLICATE_CHECK_HEADING = "Duplicate check"

# Agents the /execute-tests + incident-creation flow needs (beyond the core four).
EXECUTION_FLOW_AGENT_NAMES: set[str] = {EXECUTION_AGENT_NAME, config.IncidentCreationAgentConfig.OWN_NAME}

# The orchestrator startup + initial agent discovery can take a while to settle.
ORCHESTRATOR_READY_TIMEOUT = 120.0
AGENT_READY_TIMEOUT = 240.0
# A single webhook drives real LLM routing plus one or more full agent runs.
WEBHOOK_TIMEOUT = httpx.Timeout(1200.0)
POLL_INTERVAL = 5.0


@pytest.fixture(scope="session")
def judge_google_api_key() -> Iterator[None]:
    """Give the A/B judge the real Gemini key it calls Gemini with.

    The root conftest replaces GOOGLE_API_KEY with a dummy so no unit test can reach a real
    provider. Only the judge runs a model inside the pytest process - every other smoke test
    drives the containers, which get their key from the environment - so the configured key is
    restored just for the tests that request this fixture.
    """
    if not CONFIGURED_GOOGLE_API_KEY:
        pytest.fail(
            "GOOGLE_API_KEY is not set in the environment or in .env; the smoke suite drives real "
            "Gemini calls and cannot run without it."
        )
    dummy_key = os.environ["GOOGLE_API_KEY"]
    os.environ["GOOGLE_API_KEY"] = CONFIGURED_GOOGLE_API_KEY
    # The model factory builds the Gemini client from config, which read the dummy at import time.
    config.GOOGLE_API_KEY = CONFIGURED_GOOGLE_API_KEY
    yield
    os.environ["GOOGLE_API_KEY"] = dummy_key
    config.GOOGLE_API_KEY = dummy_key


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


def _wait_for_agents_healthy(http_client: httpx.Client, auth_headers: dict[str, str], expected_names: set[str]) -> None:
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
def all_agents_ready(http_client: httpx.Client, auth_headers: dict[str, str]) -> None:
    """Wait once until every agent the flows need is registered and healthy."""
    _wait_for_agents_healthy(http_client, auth_headers, EXPECTED_AGENT_NAMES | EXECUTION_FLOW_AGENT_NAMES)


def _post_webhook(path: str, headers: dict[str, str], payload: dict[str, str]) -> httpx.Response:
    with httpx.Client(timeout=WEBHOOK_TIMEOUT, follow_redirects=True) as client:
        return client.post(f"{ORCHESTRATOR_URL}{path}", headers=headers, json=payload)


# The flows are mutually independent: requirements review writes Jira comments;
# the test-case flow's cases end at "Review Complete" and never become executable;
# /execute-tests selects only the seeded Approved + "automated" case; the RAG sync
# involves no agent at all. So they can safely run concurrently.
_WEBHOOKS: dict[str, tuple[str, dict[str, str]]] = {
    "requirements_review": ("/new-requirements-available", {"issue_key": SEEDED_ISSUE_KEY}),
    "test_case_flow": ("/story-ready-for-test-case-generation", {"issue_key": SEEDED_ISSUE_KEY}),
    "execute_tests": ("/execute-tests", {"project_key": SEEDED_PROJECT_KEY}),
    "update_jira_db": ("/update-jira-db", {"project_key": SEEDED_PROJECT_KEY}),
    "update_confluence_db": ("/update-confluence-db", {"space_key": SEEDED_SPACE_KEY}),
    "update_test_case_db": ("/update-test-case-db", {"project_key": SEEDED_PROJECT_KEY}),
    "update_sharepoint_db": ("/update-sharepoint-db", {"drive_id": "drive-smoke"}),
}


@pytest.fixture(scope="session")
def webhook_responses(all_agents_ready: None, webhook_headers: dict[str, str]) -> dict[str, httpx.Response]:
    """Fire every webhook once, concurrently, and share the responses.

    Each webhook returns only after its whole flow completes, so posting them from
    a thread pool cuts the suite's wall time from the sum of the flows to the max.
    """
    with ThreadPoolExecutor(max_workers=len(_WEBHOOKS)) as pool:
        futures = {
            name: pool.submit(_post_webhook, path, webhook_headers, payload)
            for name, (path, payload) in _WEBHOOKS.items()
        }
        return {name: future.result() for name, future in futures.items()}


@pytest.fixture(scope="session")
def requirements_review_response(webhook_responses: dict[str, httpx.Response]) -> httpx.Response:
    return webhook_responses["requirements_review"]


@pytest.fixture(scope="session")
def test_case_flow_response(webhook_responses: dict[str, httpx.Response]) -> httpx.Response:
    return webhook_responses["test_case_flow"]


@pytest.fixture(scope="session")
def execute_tests_response(webhook_responses: dict[str, httpx.Response]) -> httpx.Response:
    return webhook_responses["execute_tests"]


@pytest.fixture(scope="session")
def update_jira_db_response(webhook_responses: dict[str, httpx.Response]) -> httpx.Response:
    return webhook_responses["update_jira_db"]


@pytest.fixture(scope="session")
def update_confluence_db_response(webhook_responses: dict[str, httpx.Response]) -> httpx.Response:
    return webhook_responses["update_confluence_db"]


@pytest.fixture(scope="session")
def update_test_case_db_response(webhook_responses: dict[str, httpx.Response]) -> httpx.Response:
    return webhook_responses["update_test_case_db"]


@pytest.fixture(scope="session")
def update_sharepoint_db_response(webhook_responses: dict[str, httpx.Response]) -> httpx.Response:
    return webhook_responses["update_sharepoint_db"]

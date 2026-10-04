# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Fixtures for the A/B suite.

The suite runs the smoke topology on a real model (``docker-compose.smoke.yml`` with the
``docker-compose.ab.yml`` override), so it shares the smoke suite's stack fixtures. The RAG syncs
run once first, since they fill the vector DB the workflows retrieve from; each workflow then runs
only when its A/B test is selected, because every run costs real model calls.
"""

import os
from collections.abc import Iterator

import httpx
import pytest

import config
from tests.conftest import CONFIGURED_GOOGLE_API_KEY
from tests.smoke import conftest as smoke_stack
from tests.smoke.conftest import (
    EXECUTION_FLOW_AGENT_NAMES,
    EXPECTED_AGENT_NAMES,
    MOCK_MODEL_NAME,
    SYNC_WEBHOOKS,
    agent_models,
    post_webhooks_concurrently,
    wait_for_agents_healthy,
)

# The stack fixtures shared with the smoke suite; pytest registers a fixture found as a module attribute.
http_client = smoke_stack.http_client
auth_headers = smoke_stack.auth_headers
webhook_headers = smoke_stack.webhook_headers


@pytest.fixture(scope="session")
def judge_google_api_key() -> Iterator[None]:
    """Give the A/B judge the real Gemini key it calls Gemini with.

    The root conftest replaces GOOGLE_API_KEY with a dummy so no unit test can reach a real
    provider. Only the judge runs a model inside the pytest process - the workflows run in the
    containers, which get their key from the environment - so the configured key is restored
    just for the tests that request this fixture.
    """
    if not CONFIGURED_GOOGLE_API_KEY:
        pytest.fail("GOOGLE_API_KEY is not set in the environment or in .env; the A/B judge cannot run without it.")
    dummy_key = os.environ["GOOGLE_API_KEY"]
    os.environ["GOOGLE_API_KEY"] = CONFIGURED_GOOGLE_API_KEY
    # The model factory builds the Gemini client from config, which read the dummy at import time.
    config.GOOGLE_API_KEY = CONFIGURED_GOOGLE_API_KEY
    yield
    os.environ["GOOGLE_API_KEY"] = dummy_key
    config.GOOGLE_API_KEY = dummy_key


@pytest.fixture(scope="session")
def real_model_agents_ready(http_client: httpx.Client, auth_headers: dict[str, str]) -> None:
    """Wait once until every agent the workflows need is healthy, and refuse a stack running the LLM mock."""
    wait_for_agents_healthy(http_client, auth_headers, EXPECTED_AGENT_NAMES | EXECUTION_FLOW_AGENT_NAMES)
    models = agent_models(http_client, auth_headers)
    if MOCK_MODEL_NAME in models.values():
        pytest.fail(
            f"The A/B suite compares what a real model produces, but the running agents report {models}. "
            "Start the stack with the docker-compose.ab.yml override."
        )


@pytest.fixture(scope="session")
def synced_knowledge_bases(real_model_agents_ready: None, webhook_headers: dict[str, str]) -> None:
    """Run the RAG syncs once, before any workflow retrieves from the vector DB they fill."""
    responses = post_webhooks_concurrently(SYNC_WEBHOOKS, webhook_headers)
    failed = {
        name: f"{response.status_code} {response.text}" for name, response in responses.items() if response.is_error
    }
    if failed:
        pytest.fail(f"The RAG syncs the workflows retrieve from failed: {failed}")

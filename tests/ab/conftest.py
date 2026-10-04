# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Fixtures for the A/B suite, which runs the smoke suite's stack on a real model."""

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
    """Give the A/B judge, the only model running in the pytest process, the real Gemini key."""
    # The root conftest replaces GOOGLE_API_KEY with a dummy so that no unit test can reach a real provider.
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
def stack_model(http_client: httpx.Client, auth_headers: dict[str, str]) -> str:
    """Wait until every agent the workflows need is healthy and return the real model they report."""
    wait_for_agents_healthy(http_client, auth_headers, EXPECTED_AGENT_NAMES | EXECUTION_FLOW_AGENT_NAMES)
    models = agent_models(http_client, auth_headers)
    if MOCK_MODEL_NAME in models.values():
        pytest.fail(
            f"The A/B suite compares what a real model produces, but the running agents report {models}. "
            "Start the stack with the docker-compose.ab.yml override."
        )
    return ", ".join(sorted(set(models.values())))


@pytest.fixture(scope="session")
def synced_knowledge_bases(stack_model: str, webhook_headers: dict[str, str]) -> None:
    """Run the RAG syncs once, before any workflow retrieves from the vector DB they fill."""
    responses = post_webhooks_concurrently(SYNC_WEBHOOKS, webhook_headers)
    failed = {
        name: f"{response.status_code} {response.text}" for name, response in responses.items() if response.is_error
    }
    if failed:
        pytest.fail(f"The RAG syncs the workflows retrieve from failed: {failed}")

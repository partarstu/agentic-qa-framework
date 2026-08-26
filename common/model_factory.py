# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Resolution of a configured model name into the model the agents talk to."""

import asyncio
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import google.auth
import httpx
from google.auth import impersonated_credentials
from google.auth.credentials import Credentials
from google.auth.exceptions import DefaultCredentialsError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token
from openai.types.shared import ReasoningEffort
from pydantic_ai.models import Model, create_async_http_client
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.profiles.qwen import qwen_model_profile
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ThinkingLevel

import config

QWEN_MODEL_PREFIX = "qwen:"
CLOUD_RUN_HOST_SUFFIX = ".run.app"
# The OpenAI client requires a non-empty key even when the endpoint expects none, be it because it
# authenticates through IAM or because it is a self-hosted server reachable only on a private network.
API_KEY_PLACEHOLDER = "not-used"
# Qwen grades thinking as low, medium or xhigh (its default) and rejects any other effort, so the thinking
# levels the agents are configured with map onto those three.
QWEN_REASONING_EFFORT_MAP: dict[ThinkingLevel, ReasoningEffort] = {
    True: "xhigh",
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "xhigh",
    "xhigh": "xhigh",
}
THINKING_DISABLED_BODY = {"chat_template_kwargs": {"enable_thinking": False}}


def build_model(model_name: str | Model, thinking_level: ThinkingLevel | None = None) -> str | Model:
    """Return the model to wrap: the self-hosted Qwen model for a "qwen:" name, the input otherwise.

    Any other name stays a plain string for pydantic-ai to infer the provider from.
    """
    if not isinstance(model_name, str) or not model_name.startswith(QWEN_MODEL_PREFIX):
        return model_name
    if not config.QWEN_ENDPOINT:
        raise ValueError(f"QWEN_ENDPOINT must be set to use the model '{model_name}'.")
    return OpenAIChatModel(
        model_name.removeprefix(QWEN_MODEL_PREFIX),
        provider=_build_qwen_provider(config.QWEN_ENDPOINT),
        profile=qwen_model_profile,
        settings=_build_qwen_settings(thinking_level),
    )


def _build_qwen_settings(thinking_level: ThinkingLevel | None) -> OpenAIChatModelSettings:
    """Thinking as Qwen expects it: switched off through its chat template, or graded through the effort.

    pydantic-ai maps the unified thinking levels onto the OpenAI efforts verbatim, which Qwen rejects for the
    two levels it does not have, so the effort is resolved here instead. It is resolved once, because every
    agent keeps the thinking level it was created with.
    """
    if not config.QWEN_THINKING_ENABLED or thinking_level is False:
        return OpenAIChatModelSettings(extra_body=THINKING_DISABLED_BODY)
    if thinking_level is None:
        return OpenAIChatModelSettings()
    return OpenAIChatModelSettings(openai_reasoning_effort=QWEN_REASONING_EFFORT_MAP[thinking_level])


def _build_qwen_provider(endpoint: str) -> OpenAIProvider:
    """The OpenAI-compatible provider for the Qwen endpoint, authenticated the way that endpoint expects."""
    audience = _cloud_run_audience(endpoint)
    if audience is None:
        return OpenAIProvider(base_url=endpoint, api_key=config.QWEN_API_KEY or API_KEY_PLACEHOLDER)
    http_client = create_async_http_client()
    http_client.auth = _CloudRunIdentityAuth(audience)
    return OpenAIProvider(base_url=endpoint, api_key=API_KEY_PLACEHOLDER, http_client=http_client)


def _cloud_run_audience(endpoint: str) -> str | None:
    """The audience an identity token for this endpoint must target, or ``None`` if it is not served by Cloud Run."""
    url = urlparse(endpoint)
    if not url.hostname or not url.hostname.endswith(CLOUD_RUN_HOST_SUFFIX):
        return None
    return f"{url.scheme}://{url.hostname}"


class _CloudRunIdentityAuth(httpx.Auth):
    """Signs every request with a Cloud Run identity token.

    A model served by Cloud Run authenticates through IAM rather than through an API key, and the identity
    tokens it accepts live at most an hour, which is shorter than the services using them run for.
    """

    def __init__(self, audience: str) -> None:
        self._credentials = _identity_token_credentials(audience)

    async def async_auth_flow(self, request: httpx.Request) -> AsyncIterator[httpx.Request]:
        if not self._credentials.valid:
            await asyncio.to_thread(self._credentials.refresh, GoogleAuthRequest())
        request.headers["Authorization"] = f"Bearer {self._credentials.token}"
        yield request


def _identity_token_credentials(audience: str) -> Credentials:
    """Application default credentials able to issue identity tokens for a Cloud Run service.

    A service account key file and the metadata server of a service deployed in Google Cloud issue those
    tokens themselves; a local gcloud login impersonating an invoker service account derives them from it.
    """
    try:
        return id_token.fetch_id_token_credentials(audience)
    except DefaultCredentialsError:
        source_credentials, _ = google.auth.default()
        return impersonated_credentials.IDTokenCredentials(source_credentials, target_audience=audience)

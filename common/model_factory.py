# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Resolution of a configured model name into the model the agents talk to."""

import asyncio
from collections.abc import AsyncIterator, Callable
from urllib.parse import urlparse

import google.auth
import httpx2
from anthropic import AsyncAnthropic
from google.auth import impersonated_credentials
from google.auth.credentials import Credentials
from google.auth.exceptions import DefaultCredentialsError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.genai import Client as GoogleGenaiClient
from google.genai.types import HttpOptions, HttpRetryOptions
from google.oauth2 import id_token
from openai import AsyncOpenAI
from openai.types.shared import ReasoningEffort
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.profiles.qwen import qwen_model_profile
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.retries import AsyncHTTPX2TenacityTransport, RetryConfig, wait_retry_after
from pydantic_ai.settings import ThinkingLevel
from tenacity import RetryCallState, retry_if_exception_type, stop_after_attempt, wait_exponential

import config
from common import utils

logger = utils.get_logger("model_factory")

QWEN_MODEL_PREFIX = "qwen:"
ANTHROPIC_PROVIDER_PREFIX = "anthropic:"
GOOGLE_PROVIDER_PREFIX = "google-gla:"
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
# Qwen3.8's model card sampling for thinking mode, where it warns that greedy decoding repeats endlessly; its
# top_k of 20 comes from the checkpoint's generation config, which the server applies when a request omits it.
QWEN_THINKING_TEMPERATURE = 1.0
QWEN_THINKING_TOP_P = 0.95
CLAUDE_5_PREFIXES = ("claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-mythos-5")
# Models whose API rejects explicitly disabled thinking: they run adaptive at effort low instead.
DISABLED_THINKING_UNSUPPORTED_PREFIXES = ("claude-fable-5", "claude-mythos-5")
# HTTP statuses retried at the transport boundary (the model endpoints sit behind serverless front ends).
RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})
# Models whose disabled-thinking fallback has already been logged, so construction logs one WARNING only.
_logged_thinking_fallbacks: set[str] = set()


def is_claude_5(model_name: object) -> bool:
    """Return whether a pydantic-ai model name identifies a Claude 5 family model."""
    return isinstance(model_name, str) and model_name.split(":")[-1].startswith(CLAUDE_5_PREFIXES)


def build_claude_5_settings(
    thinking_level: ThinkingLevel | None, max_output_tokens: int | None, model_name: str = ""
) -> AnthropicModelSettings:
    """Build Claude 5 settings without unsupported sampling fields or token budgets.

    Models that reject disabled thinking fall back to adaptive thinking at effort ``low``; the
    fallback is logged once per model.
    """
    settings: AnthropicModelSettings = {}
    if max_output_tokens is not None:
        settings["max_tokens"] = max_output_tokens
    if thinking_level is None:
        return settings
    if thinking_level is False:
        if model_name.split(":")[-1].startswith(DISABLED_THINKING_UNSUPPORTED_PREFIXES):
            if model_name not in _logged_thinking_fallbacks:
                _logged_thinking_fallbacks.add(model_name)
                logger.warning(
                    "Model '%s' rejects disabled thinking; falling back to adaptive thinking at effort 'low'.",
                    model_name,
                )
            settings["anthropic_thinking"] = {"type": "adaptive"}
            settings["anthropic_effort"] = "low"
        else:
            settings["anthropic_thinking"] = {"type": "disabled"}
    elif thinking_level is True:
        settings["anthropic_thinking"] = {"type": "adaptive"}
    else:
        effort = "low" if thinking_level == "minimal" else str(thinking_level)
        settings["anthropic_thinking"] = {"type": "adaptive"}
        settings["anthropic_effort"] = effort
    return settings


def build_model(model_name: str | Model, thinking_level: ThinkingLevel | None = None) -> str | Model:
    """Return the model to wrap: the provider model built for a known provider, the input otherwise.

    Qwen is served by a self-hosted OpenAI-compatible endpoint; Claude and Gemini are built
    explicitly so their HTTP clients carry the transport-level retry. Any other name stays
    a plain string for pydantic-ai to infer the provider from.
    """
    if not isinstance(model_name, str):
        return model_name
    if model_name.startswith(QWEN_MODEL_PREFIX):
        if not config.QWEN_ENDPOINT:
            raise ValueError(f"QWEN_ENDPOINT must be set to use the model '{model_name}'.")
        qwen_model_name = model_name.removeprefix(QWEN_MODEL_PREFIX)
        return OpenAIChatModel(
            qwen_model_name,
            provider=_build_qwen_provider(config.QWEN_ENDPOINT, model_name),
            profile=qwen_model_profile(qwen_model_name),
            settings=_build_qwen_settings(thinking_level),
        )
    if model_name.startswith(ANTHROPIC_PROVIDER_PREFIX) or is_claude_5(model_name):
        return _build_anthropic_model(model_name)
    if model_name.startswith(GOOGLE_PROVIDER_PREFIX):
        return _build_google_model(model_name)
    return model_name


def _build_anthropic_model(model_name: str) -> AnthropicModel:
    """The Anthropic model with the SDK's own retries disabled in favour of the retry transport."""
    client = AsyncAnthropic(
        api_key=config.ANTHROPIC_API_KEY,
        max_retries=0,
        http_client=_retry_http_client(model_name),
    )
    return AnthropicModel(
        model_name.removeprefix(ANTHROPIC_PROVIDER_PREFIX),
        provider=AnthropicProvider(anthropic_client=client),
    )


def _build_google_model(model_name: str) -> GoogleModel:
    """The Gemini model with the SDK's own retries disabled in favour of the retry transport."""
    client = GoogleGenaiClient(
        vertexai=False,
        api_key=config.GOOGLE_API_KEY,
        http_options=HttpOptions(
            httpx_async_client=_retry_http_client(model_name),
            retry_options=HttpRetryOptions(attempts=1),
        ),
    )
    return GoogleModel(model_name.removeprefix(GOOGLE_PROVIDER_PREFIX), provider=GoogleProvider(client=client))


def _retry_http_client(model_name: str) -> httpx2.AsyncClient:
    """An HTTP client retrying transport errors and 429/502/503/504 within the agent-run retry budget, honouring the delay the provider asks for."""
    transport = AsyncHTTPX2TenacityTransport(
        config=RetryConfig(
            stop=stop_after_attempt(config.RetryConfig.MAX_RETRIES),
            wait=wait_retry_after(
                fallback_strategy=_wait_body_retry_delay(
                    wait_exponential(multiplier=config.RetryConfig.RETRY_BASE_DELAY_SECONDS)
                ),
                max_wait=config.RetryConfig.PROVIDER_RETRY_DELAY_CAP_SECONDS,
            ),
            retry=retry_if_exception_type((httpx2.TransportError, httpx2.HTTPStatusError)),
            before_sleep=_log_retry_attempt(model_name),
            reraise=True,
        ),
        wrapped=_RetryableBodyReadingTransport(),
        validate_response=_raise_if_retryable_status,
    )
    return httpx2.AsyncClient(transport=transport)


class _RetryableBodyReadingTransport(httpx2.AsyncBaseTransport):
    """Reads the body of a retryable response, which the retry wait parses the provider's requested delay from."""

    def __init__(self) -> None:
        self._wrapped = httpx2.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        response = await self._wrapped.handle_async_request(request)
        if response.status_code in RETRYABLE_STATUS_CODES:
            await response.aread()
        return response

    async def aclose(self) -> None:
        await self._wrapped.aclose()


def _raise_if_retryable_status(response: httpx2.Response) -> None:
    """Raise (and so retry) only the statuses the transport level owns; every other response passes."""
    if response.status_code in RETRYABLE_STATUS_CODES:
        response.raise_for_status()


# Gemini names the wait a quota needs only in the response body and sends no Retry-After header.
def _wait_body_retry_delay(fallback_strategy: Callable[[RetryCallState], float]) -> Callable[[RetryCallState], float]:
    """A wait honouring the capped ``google.rpc.RetryInfo`` delay of a response body, else the fallback."""

    def wait(retry_state: RetryCallState) -> float:
        exception = retry_state.outcome.exception() if retry_state.outcome else None
        if isinstance(exception, httpx2.HTTPStatusError):
            delay = _body_retry_delay_seconds(exception.response)
            if delay is not None:
                return min(delay, config.RetryConfig.PROVIDER_RETRY_DELAY_CAP_SECONDS)
        return fallback_strategy(retry_state)

    return wait


def _body_retry_delay_seconds(response: httpx2.Response) -> float | None:
    for detail in _error_payload(response).get("details") or []:
        if isinstance(detail, dict) and str(detail.get("@type", "")).endswith("google.rpc.RetryInfo"):
            try:
                return float(str(detail.get("retryDelay", "")).removesuffix("s"))
            except ValueError:
                return None
    return None


def _error_payload(response: httpx2.Response) -> dict:
    try:
        payload = response.json()
    except (httpx2.ResponseNotRead, ValueError):
        return {}
    error = payload.get("error") if isinstance(payload, dict) else None
    return error if isinstance(error, dict) else {}


def _log_retry_attempt(model_name: str) -> Callable[[RetryCallState], None]:
    """The ``before_sleep`` hook logging one line per transport-level retry attempt."""

    def log_attempt(retry_state: RetryCallState) -> None:
        exception = retry_state.outcome.exception() if retry_state.outcome else None
        if isinstance(exception, httpx2.HTTPStatusError):
            reason = f"HTTP {exception.response.status_code}"
            if provider_message := _error_payload(exception.response).get("message"):
                reason += f": {provider_message}"
        else:
            reason = type(exception).__name__ if exception is not None else "unknown"
        delay = retry_state.next_action.sleep if retry_state.next_action else 0
        logger.warning(
            "LLM provider request for '%s' failed (attempt %s/%s, reason: %s); retrying in %.1fs",
            model_name,
            retry_state.attempt_number,
            config.RetryConfig.MAX_RETRIES,
            reason,
            delay,
        )

    return log_attempt


def _build_qwen_settings(thinking_level: ThinkingLevel | None) -> OpenAIChatModelSettings:
    """Return Qwen's thinking settings: off via its chat template, or model-card sampling plus any effort."""
    if not config.QWEN_THINKING_ENABLED or thinking_level is False:
        return OpenAIChatModelSettings(extra_body=THINKING_DISABLED_BODY)
    settings = OpenAIChatModelSettings(temperature=QWEN_THINKING_TEMPERATURE, top_p=QWEN_THINKING_TOP_P)
    if thinking_level is not None:
        settings["openai_reasoning_effort"] = QWEN_REASONING_EFFORT_MAP[thinking_level]
    return settings


def _build_qwen_provider(endpoint: str, model_name: str) -> OpenAIProvider:
    """The OpenAI-compatible provider for the Qwen endpoint, authenticated the way that endpoint expects."""
    audience = _cloud_run_audience(endpoint)
    if audience is None:
        client = AsyncOpenAI(
            base_url=endpoint,
            api_key=config.QWEN_API_KEY or API_KEY_PLACEHOLDER,
            max_retries=0,
            http_client=_retry_http_client(model_name),
        )
        return OpenAIProvider(openai_client=client)
    http_client = _retry_http_client(model_name)
    http_client.auth = _CloudRunIdentityAuth(audience)
    client = AsyncOpenAI(base_url=endpoint, api_key=API_KEY_PLACEHOLDER, max_retries=0, http_client=http_client)
    return OpenAIProvider(openai_client=client)


def _cloud_run_audience(endpoint: str) -> str | None:
    """The audience an identity token for this endpoint must target, or ``None`` if it is not served by Cloud Run."""
    url = urlparse(endpoint)
    if not url.hostname or not url.hostname.endswith(CLOUD_RUN_HOST_SUFFIX):
        return None
    return f"{url.scheme}://{url.hostname}"


class _CloudRunIdentityAuth(httpx2.Auth):
    """Signs every request with a Cloud Run identity token.

    A model served by Cloud Run authenticates through IAM rather than through an API key, and the identity
    tokens it accepts live at most an hour, which is shorter than the services using them run for.
    """

    def __init__(self, audience: str) -> None:
        self._credentials = _identity_token_credentials(audience)
        # The credentials object is read and refreshed across an await, so concurrent requests
        # would otherwise all refresh at once and mutate it while another one reads it.
        self._lock = asyncio.Lock()

    async def async_auth_flow(self, request: httpx2.Request) -> AsyncIterator[httpx2.Request]:
        async with self._lock:
            if not self._credentials.valid:
                await asyncio.to_thread(self._credentials.refresh, GoogleAuthRequest())
            token = self._credentials.token
        request.headers["Authorization"] = f"Bearer {token}"
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

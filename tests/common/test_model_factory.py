# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2
import pytest
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.retries import AsyncHTTPX2TenacityTransport

import config
from common.model_factory import (
    _CloudRunIdentityAuth,
    _RetryableBodyReadingTransport,
    _wait_body_retry_delay,
    build_claude_5_settings,
    build_model,
)

CLOUD_RUN_ENDPOINT = "https://qwen-3-8-123456.europe-west4.run.app/v1/"


def test_non_qwen_name_is_left_to_pydantic_ai():
    assert build_model("some-other-model") == "some-other-model"


def test_google_name_builds_gemini_model_with_retry_transport():
    model = build_model("google-gla:gemini-3.5-flash")

    assert isinstance(model, GoogleModel)
    transport = model.client._api_client._async_httpx_client._transport
    assert isinstance(transport, AsyncHTTPX2TenacityTransport)


def test_anthropic_name_builds_anthropic_model_with_retry_transport():
    model = build_model("anthropic:claude-opus-5")

    assert isinstance(model, AnthropicModel)
    transport = model.client._client._transport
    assert isinstance(transport, AsyncHTTPX2TenacityTransport)


def test_model_instance_is_left_untouched():
    model = MagicMock(spec=Model)
    assert build_model(model) is model


def test_qwen_name_without_endpoint_is_rejected():
    with patch("config.QWEN_ENDPOINT", ""), pytest.raises(ValueError, match="QWEN_ENDPOINT"):
        build_model("qwen:Qwen/Qwen3.8-27B-FP8")


def test_qwen_model_uses_configured_endpoint_and_key():
    with patch("config.QWEN_ENDPOINT", "http://localhost:8080/v1/"), patch("config.QWEN_API_KEY", "local-key"):
        model = build_model("qwen:Qwen/Qwen3.8-27B-FP8")

    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "Qwen/Qwen3.8-27B-FP8"
    assert model.base_url == "http://localhost:8080/v1/"
    assert model.client.api_key == "local-key"
    assert isinstance(model.client._client._transport, AsyncHTTPX2TenacityTransport)
    assert model.profile["ignore_streamed_leading_whitespace"] is True


@pytest.mark.parametrize(
    ("thinking_level", "expected_effort"),
    [("minimal", "low"), ("low", "low"), ("medium", "medium"), ("high", "xhigh"), ("xhigh", "xhigh"), (True, "xhigh")],
)
def test_agent_thinking_level_is_graded_as_a_reasoning_effort_qwen_accepts(thinking_level, expected_effort):
    with patch("config.QWEN_ENDPOINT", "http://localhost:8080/v1/"), patch("config.QWEN_THINKING_ENABLED", True):
        model = build_model("qwen:Qwen/Qwen3.8-27B-FP8", thinking_level)

    assert model.settings == {"temperature": 1.0, "top_p": 0.95, "openai_reasoning_effort": expected_effort}


def test_qwen_default_effort_applies_without_a_thinking_level():
    with patch("config.QWEN_ENDPOINT", "http://localhost:8080/v1/"), patch("config.QWEN_THINKING_ENABLED", True):
        model = build_model("qwen:Qwen/Qwen3.8-27B-FP8")

    assert model.settings == {"temperature": 1.0, "top_p": 0.95}


@pytest.mark.parametrize("thinking_level", ["medium", False, None])
def test_disabled_thinking_switches_qwen_off_through_its_chat_template(thinking_level):
    with (
        patch("config.QWEN_ENDPOINT", "http://localhost:8080/v1/"),
        patch("config.QWEN_THINKING_ENABLED", False),
    ):
        model = build_model("qwen:Qwen/Qwen3.8-27B-FP8", thinking_level)

    assert model.settings == {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}


@patch("common.model_factory._identity_token_credentials")
def test_cloud_run_endpoint_is_authenticated_with_an_identity_token(mock_credentials):
    with patch("config.QWEN_ENDPOINT", CLOUD_RUN_ENDPOINT), patch("config.QWEN_API_KEY", "unused"):
        model = build_model("qwen:Qwen/Qwen3.8-27B-FP8")

    mock_credentials.assert_called_once_with("https://qwen-3-8-123456.europe-west4.run.app")
    assert isinstance(model.client._client.auth, _CloudRunIdentityAuth)


@pytest.mark.asyncio
@patch("common.model_factory._identity_token_credentials")
async def test_identity_token_is_refreshed_once_expired(mock_credentials):
    credentials = MagicMock(valid=False, token="minted-token")
    credentials.refresh.side_effect = lambda _request: setattr(credentials, "valid", True)
    mock_credentials.return_value = credentials
    auth = _CloudRunIdentityAuth("https://qwen-3-8-123456.europe-west4.run.app")

    async def sign() -> httpx2.Request:
        request = httpx2.Request("POST", f"{CLOUD_RUN_ENDPOINT}chat/completions")
        return await anext(auth.async_auth_flow(request))

    assert (await sign()).headers["Authorization"] == "Bearer minted-token"
    assert (await sign()).headers["Authorization"] == "Bearer minted-token"
    credentials.refresh.assert_called_once()


def test_retry_transport_retries_retryable_status_and_logs_the_attempt(caplog, monkeypatch):
    import asyncio

    monkeypatch.setattr(config.RetryConfig, "RETRY_BASE_DELAY_SECONDS", 0.01)
    client = build_model("google-gla:gemini-3.5-flash").client._api_client._async_httpx_client
    calls = []

    class _StubTransport(httpx2.AsyncBaseTransport):
        async def handle_async_request(self, request):
            calls.append(request)
            return httpx2.Response(503) if len(calls) == 1 else httpx2.Response(200)

    client._transport.wrapped = _StubTransport()

    with caplog.at_level(logging.WARNING, logger="model_factory"):
        response = asyncio.run(client.get("http://model.test/complete"))

    assert response.status_code == 200
    assert len(calls) == 2
    retry_line = next(record for record in caplog.records if "HTTP 503" in record.message)
    assert "attempt 1/3" in retry_line.message
    assert "retrying in" in retry_line.message


def test_anthropic_retry_logs_the_http_status(caplog, monkeypatch):
    import asyncio

    monkeypatch.setattr(config.RetryConfig, "RETRY_BASE_DELAY_SECONDS", 0.01)
    client = build_model("anthropic:claude-sonnet-5").client._client
    calls = []

    class _StubTransport(httpx2.AsyncBaseTransport):
        async def handle_async_request(self, request):
            calls.append(request)
            return httpx2.Response(429) if len(calls) == 1 else httpx2.Response(200)

    client._transport.wrapped = _StubTransport()

    with caplog.at_level(logging.WARNING, logger="model_factory"):
        response = asyncio.run(client.get("http://model.test/complete"))

    assert response.status_code == 200
    assert any("reason: HTTP 429" in record.message for record in caplog.records)


def test_retry_transport_propagates_client_errors_untouched():
    import asyncio

    client = build_model("google-gla:gemini-3.5-flash").client._api_client._async_httpx_client
    calls = []

    class _StubTransport(httpx2.AsyncBaseTransport):
        async def handle_async_request(self, request):
            calls.append(request)
            return httpx2.Response(400)

    client._transport.wrapped = _StubTransport()

    response = asyncio.run(client.get("http://model.test/complete"))

    assert response.status_code == 400
    assert len(calls) == 1


def _retry_state_for(response: httpx2.Response) -> MagicMock:
    error = httpx2.HTTPStatusError(
        "rate limited", request=httpx2.Request("POST", "http://model.test"), response=response
    )
    return MagicMock(outcome=MagicMock(exception=MagicMock(return_value=error)))


def _gemini_quota_response(retry_delay: str) -> httpx2.Response:
    return httpx2.Response(
        429,
        json={
            "error": {
                "code": 429,
                "message": "Quota exceeded for metric: generate_content_paid_tier_input_token_count",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": []},
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry_delay},
                ],
            }
        },
    )


FALLBACK_WAIT_SECONDS = 5.0


@pytest.mark.parametrize(
    ("response", "expected_wait"),
    [
        (_gemini_quota_response("34s"), 34.0),
        (_gemini_quota_response("0.5s"), 0.5),
        (_gemini_quota_response("600s"), config.RetryConfig.PROVIDER_RETRY_DELAY_CAP_SECONDS),
        (_gemini_quota_response("soon"), FALLBACK_WAIT_SECONDS),
        (httpx2.Response(429, json={"error": {"message": "slow down"}}), FALLBACK_WAIT_SECONDS),
        (httpx2.Response(503, text="<html>unavailable</html>"), FALLBACK_WAIT_SECONDS),
        (httpx2.Response(429, json=[{"error": {}}]), FALLBACK_WAIT_SECONDS),
    ],
)
def test_retry_wait_honours_the_capped_retry_delay_of_the_body(response, expected_wait):
    wait = _wait_body_retry_delay(lambda _state: FALLBACK_WAIT_SECONDS)

    assert wait(_retry_state_for(response)) == expected_wait


def test_retry_wait_falls_back_for_a_transport_error():
    state = MagicMock(outcome=MagicMock(exception=MagicMock(return_value=httpx2.ConnectError("refused"))))

    assert _wait_body_retry_delay(lambda _state: FALLBACK_WAIT_SECONDS)(state) == FALLBACK_WAIT_SECONDS


@pytest.mark.parametrize(("status_code", "body_is_read"), [(429, True), (503, True), (400, False), (200, False)])
def test_body_reading_transport_reads_only_retryable_responses(status_code, body_is_read):
    import asyncio

    class _Body(httpx2.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"error": {}}'

    transport = _RetryableBodyReadingTransport()
    transport._wrapped = MagicMock(
        handle_async_request=AsyncMock(return_value=httpx2.Response(status_code, stream=_Body()))
    )

    response = asyncio.run(transport.handle_async_request(httpx2.Request("POST", "http://model.test")))

    assert response.is_stream_consumed is body_is_read


def test_gemini_retry_logs_the_provider_message(caplog, monkeypatch):
    import asyncio

    monkeypatch.setattr(config.RetryConfig, "PROVIDER_RETRY_DELAY_CAP_SECONDS", 0.01)
    client = build_model("google-gla:gemini-3.5-flash").client._api_client._async_httpx_client
    calls = []

    class _StubTransport(httpx2.AsyncBaseTransport):
        async def handle_async_request(self, request):
            calls.append(request)
            return _gemini_quota_response("34s") if len(calls) == 1 else httpx2.Response(200)

    client._transport.wrapped = _StubTransport()

    with caplog.at_level(logging.WARNING, logger="model_factory"):
        response = asyncio.run(client.get("http://model.test/complete"))

    assert response.status_code == 200
    retry_line = next(record.message for record in caplog.records if "HTTP 429" in record.message)
    assert "Quota exceeded for metric: generate_content_paid_tier_input_token_count" in retry_line


def test_claude_5_settings_per_thinking_level():
    assert build_claude_5_settings(None, None, "claude-opus-5") == {}
    assert build_claude_5_settings(False, None, "claude-opus-5") == {"anthropic_thinking": {"type": "disabled"}}
    assert build_claude_5_settings(True, None, "claude-opus-5") == {"anthropic_thinking": {"type": "adaptive"}}
    assert build_claude_5_settings("minimal", None, "claude-opus-5") == {
        "anthropic_thinking": {"type": "adaptive"},
        "anthropic_effort": "low",
    }
    assert build_claude_5_settings("xhigh", None, "claude-opus-5") == {
        "anthropic_thinking": {"type": "adaptive"},
        "anthropic_effort": "xhigh",
    }


def test_claude_5_settings_carry_max_tokens_only_when_set():
    assert build_claude_5_settings(None, None, "claude-opus-5") == {}
    assert build_claude_5_settings(None, 4096, "claude-opus-5") == {"max_tokens": 4096}


@pytest.mark.parametrize(
    "settings",
    [
        build_claude_5_settings(level, 2048, "claude-opus-5")
        for level in (None, False, True, "minimal", "low", "medium", "high", "xhigh")
    ],
)
def test_claude_5_settings_never_carry_forbidden_fields(settings):
    forbidden = {"temperature", "top_p", "top_k", "anthropic_thinking_budget_tokens", "budget_tokens"}
    assert not forbidden & set(settings)


def test_claude_5_models_rejecting_disabled_thinking_fall_back_to_adaptive_low(caplog):
    with caplog.at_level(logging.WARNING, logger="model_factory"):
        settings = build_claude_5_settings(False, None, "claude-fable-5")

    assert settings == {"anthropic_thinking": {"type": "adaptive"}, "anthropic_effort": "low"}
    assert any("claude-fable-5" in record.message for record in caplog.records)

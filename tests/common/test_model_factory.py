# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from unittest.mock import MagicMock, patch

import httpx
import pytest
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel

from common.model_factory import _CloudRunIdentityAuth, build_model

CLOUD_RUN_ENDPOINT = "https://qwen-3-8-123456.europe-west4.run.app/v1/"


def test_non_qwen_name_is_left_to_pydantic_ai():
    assert build_model("google-gla:gemini-3.5-flash") == "google-gla:gemini-3.5-flash"


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


@pytest.mark.parametrize(
    ("thinking_level", "expected_effort"),
    [("minimal", "low"), ("low", "low"), ("medium", "medium"), ("high", "xhigh"), ("xhigh", "xhigh"), (True, "xhigh")],
)
def test_agent_thinking_level_is_graded_as_a_reasoning_effort_qwen_accepts(thinking_level, expected_effort):
    with patch("config.QWEN_ENDPOINT", "http://localhost:8080/v1/"):
        model = build_model("qwen:Qwen/Qwen3.8-27B-FP8", thinking_level)

    assert model.settings["openai_reasoning_effort"] == expected_effort
    assert "extra_body" not in model.settings


def test_qwen_default_effort_applies_without_a_thinking_level():
    with patch("config.QWEN_ENDPOINT", "http://localhost:8080/v1/"):
        model = build_model("qwen:Qwen/Qwen3.8-27B-FP8")

    assert model.settings == {}


@pytest.mark.parametrize("thinking_level", ["medium", False, None])
def test_disabled_thinking_switches_qwen_off_through_its_chat_template(thinking_level):
    with (
        patch("config.QWEN_ENDPOINT", "http://localhost:8080/v1/"),
        patch("config.QWEN_THINKING_ENABLED", False),
    ):
        model = build_model("qwen:Qwen/Qwen3.8-27B-FP8", thinking_level)

    assert model.settings["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert "openai_reasoning_effort" not in model.settings


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

    async def sign() -> httpx.Request:
        request = httpx.Request("POST", f"{CLOUD_RUN_ENDPOINT}chat/completions")
        return await anext(auth.async_auth_flow(request))

    assert (await sign()).headers["Authorization"] == "Bearer minted-token"
    assert (await sign()).headers["Authorization"] == "Bearer minted-token"
    credentials.refresh.assert_called_once()

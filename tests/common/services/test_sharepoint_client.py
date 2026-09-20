# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the Microsoft Graph client of the SharePoint ingestion (WS18)."""

from unittest.mock import patch

import httpx
import pytest

from common.services.sharepoint_client import (
    GRAPH_SCOPE,
    RETRY_BACKOFF_CAP_SECONDS,
    DeltaResyncRequired,
    SharePointClient,
)

DRIVE_ID = "drive-1"
GRAPH_BASE_URL = "https://graph.test/v1.0"
TOKEN_URL = "https://login.test/tenant/oauth2/v2.0/token"


@pytest.fixture
def sharepoint_config():
    with (
        patch("config.SharePointConfig.TENANT_ID", "tenant"),
        patch("config.SharePointConfig.CLIENT_ID", "client"),
        patch("config.SharePointConfig.CLIENT_SECRET", "secret"),
        patch("config.SharePointConfig.AUTHORITY_URL", "https://login.test"),
        patch("config.SharePointConfig.GRAPH_BASE_URL", GRAPH_BASE_URL),
    ):
        yield


@pytest.fixture
def token_endpoint(sharepoint_config):
    """The Entra token endpoint; answers with a one-hour token unless a test says otherwise."""
    with patch(
        "common.services.sharepoint_client.httpx.post",
        return_value=httpx.Response(200, json={"access_token": "token-1", "expires_in": 3600}),
    ) as post:
        yield post


def _serve(handler):
    """Route the client's Graph calls to ``handler`` while keeping the client's own settings."""
    real_client = httpx.Client
    return patch(
        "common.services.sharepoint_client.httpx.Client",
        side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_missing_credentials_are_named():
    with (
        patch("config.SharePointConfig.TENANT_ID", "tenant"),
        patch("config.SharePointConfig.CLIENT_ID", None),
        patch("config.SharePointConfig.CLIENT_SECRET", ""),
        pytest.raises(ValueError, match="SHAREPOINT_CLIENT_ID, SHAREPOINT_CLIENT_SECRET"),
    ):
        SharePointClient()


def test_the_token_comes_from_the_client_credentials_grant_and_is_cached(token_endpoint):
    client = SharePointClient()

    assert client._access_token() == "token-1"
    assert client._access_token() == "token-1"

    token_endpoint.assert_called_once()
    assert token_endpoint.call_args.args[0] == TOKEN_URL
    assert token_endpoint.call_args.kwargs["data"] == {
        "grant_type": "client_credentials",
        "client_id": "client",
        "client_secret": "secret",
        "scope": GRAPH_SCOPE,
    }


def test_a_rejected_token_request_names_the_reason(token_endpoint):
    token_endpoint.return_value = httpx.Response(401, json={"error_description": "consent missing"})

    with pytest.raises(RuntimeError, match="consent missing"):
        SharePointClient()._access_token()


def test_a_token_request_answered_without_json_names_the_status(token_endpoint):
    token_endpoint.return_value = httpx.Response(502, text="Bad Gateway")

    with pytest.raises(RuntimeError, match="HTTP 502"):
        SharePointClient()._access_token()


def test_a_throttled_call_honours_retry_after(token_endpoint):
    responses = iter([httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(200, json={"value": []})])

    with _serve(lambda request: next(responses)), patch("common.services.sharepoint_client.time.sleep") as sleep:
        page = SharePointClient().enumerate_delta(DRIVE_ID)

    assert page == {"value": []}
    sleep.assert_called_once_with(3.0)


def test_an_expired_delta_link_requires_a_full_resync(token_endpoint):
    with _serve(lambda request: httpx.Response(410)), pytest.raises(DeltaResyncRequired):
        SharePointClient().enumerate_delta(DRIVE_ID, f"{GRAPH_BASE_URL}/drives/{DRIVE_ID}/root/delta?token=expired")


@pytest.mark.parametrize(
    "delta_link",
    ["https://evil.test/v1.0/drives/drive-1/root/delta", "http://graph.test/v1.0/drives/drive-1/root/delta"],
    ids=["another_host", "another_scheme"],
)
def test_a_delta_link_outside_the_graph_origin_is_never_followed(token_endpoint, delta_link):
    """The stored link comes from response data and the request carries the bearer token."""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, json={"value": []})

    with _serve(handler), pytest.raises(DeltaResyncRequired, match="Graph origin"):
        SharePointClient().enumerate_delta(DRIVE_ID, delta_link)

    assert requested == []


def test_an_uncapped_retry_after_is_bounded_by_the_back_off_cap(token_endpoint):
    responses = iter([httpx.Response(429, headers={"Retry-After": "86400"}), httpx.Response(200, json={"value": []})])

    with _serve(lambda request: next(responses)), patch("common.services.sharepoint_client.time.sleep") as sleep:
        SharePointClient().enumerate_delta(DRIVE_ID)

    sleep.assert_called_once_with(RETRY_BACKOFF_CAP_SECONDS)


def test_a_retry_after_http_date_falls_back_to_the_back_off(token_endpoint):
    """Retry-After is legally an HTTP-date too; it must not escape the retry loop as a ValueError."""
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
            httpx.Response(200, json={"value": []}),
        ]
    )

    with _serve(lambda request: next(responses)), patch("common.services.sharepoint_client.time.sleep") as sleep:
        SharePointClient().enumerate_delta(DRIVE_ID)

    sleep.assert_called_once_with(1)


def test_a_download_follows_the_redirect_without_leaking_the_token(token_endpoint):
    download_url = "https://tenant.sharepoint.com/download.aspx?tempauth=abc"
    seen_downloads: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "graph.test":
            assert request.headers["Authorization"] == "Bearer token-1"
            return httpx.Response(302, headers={"Location": download_url})
        seen_downloads.append(request)
        return httpx.Response(200, content=b"file-bytes")

    with _serve(handler):
        content = SharePointClient().download_item(DRIVE_ID, "item-1")

    assert content == b"file-bytes"
    assert len(seen_downloads) == 1
    assert "Authorization" not in seen_downloads[0].headers


def test_a_delta_enumeration_starts_at_the_configured_drive_root(token_endpoint):
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, json={"value": []})

    with _serve(handler):
        SharePointClient().enumerate_delta(DRIVE_ID)

    assert requested == [f"{GRAPH_BASE_URL}/drives/{DRIVE_ID}/root/delta"]

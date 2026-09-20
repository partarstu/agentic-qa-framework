# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Microsoft Graph access for SharePoint document libraries.

App-only tokens come from Entra's client-credentials grant, one form POST to the tenant's
``/oauth2/v2.0/token`` endpoint (the flow MSAL wraps; MSAL itself only accepts an HTTPS authority,
which rules out a hermetic mock); the least-privilege setup is the ``Sites.Selected`` application
permission granted per site. Graph itself is called over httpx with explicit timeouts and 429/5xx
back-off that honours ``Retry-After``.

Change detection uses delta enumeration on the drive root: the caller pages through
``@odata.nextLink`` to a final ``@odata.deltaLink``; deletions arrive with the ``deleted``
facet; a ``410 Gone`` means the stored delta link expired and a fresh full enumeration is
required.
"""

import time

import httpx

import config
from common import utils

logger = utils.get_logger("sharepoint_client")

GRAPH_SCOPE = "https://graph.microsoft.com/.default"
# Retries for 429/5xx responses, honouring Retry-After within the back-off cap.
MAX_RETRIES = 5
RETRY_BACKOFF_CAP_SECONDS = 32.0
TIMEOUT_SECONDS = 30.0


class DeltaResyncRequired(Exception):
    """The stored delta link expired (410 Gone); a full enumeration must start again."""


class SharePointClient:
    """A thin authenticated Microsoft Graph client for one tenant's drives."""

    def __init__(self) -> None:
        tenant_id = config.SharePointConfig.TENANT_ID
        client_id = config.SharePointConfig.CLIENT_ID
        client_secret = config.SharePointConfig.CLIENT_SECRET
        missing = [
            name
            for name, value in (("TENANT_ID", tenant_id), ("CLIENT_ID", client_id), ("CLIENT_SECRET", client_secret))
            if not value
        ]
        if missing:
            raise ValueError(f"SharePoint access requires SHAREPOINT_{', SHAREPOINT_'.join(missing)} to be set.")
        self._token_url = f"{config.SharePointConfig.AUTHORITY_URL}/{tenant_id}/oauth2/v2.0/token"
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._token_expiry = 0.0

    def _access_token(self) -> str:
        """A cached app-only token, refreshed five minutes before it expires."""
        if self._token is None or time.monotonic() >= self._token_expiry - 300:
            response = httpx.post(
                self._token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "scope": GRAPH_SCOPE,
                },
                timeout=TIMEOUT_SECONDS,
            )
            result = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            if response.status_code != 200 or "access_token" not in result:
                reason = result.get("error_description") or f"HTTP {response.status_code}"
                raise RuntimeError(f"SharePoint token acquisition failed: {reason}")
            self._token = result["access_token"]
            self._token_expiry = time.monotonic() + int(result.get("expires_in", 3600))
        return self._token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token()}"}

    def _request_with_retry(self, method: str, url: str) -> httpx.Response:
        """One Graph call with 429/5xx back-off that honours Retry-After.

        Redirects are followed: a file download answers 302 with a pre-authenticated URL, and httpx drops
        the Authorization header when the redirect leaves the Graph origin.
        """
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
            for attempt in range(MAX_RETRIES):
                response = client.request(method, url, headers=self._headers())
                if response.status_code == 410:
                    # The caller must distinguish this from other failures: it changes the
                    # enumeration strategy, it is not a retryable blip.
                    return response
                if response.status_code in (429, 502, 503, 504) and attempt < MAX_RETRIES - 1:
                    delay = utils.retry_delay(response.headers.get("Retry-After"), attempt, RETRY_BACKOFF_CAP_SECONDS)
                    logger.warning(
                        "Graph %s %s returned %s; retrying in %.0fs.", method, url, response.status_code, delay
                    )
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                return response
        raise RuntimeError(f"Graph {method} {url} failed after {MAX_RETRIES} attempts.")

    def enumerate_delta(self, drive_id: str, delta_link: str | None = None) -> dict:
        """One delta page: the response's ``value`` plus the next/delta link it carries.

        A ``delta_link`` of ``None`` starts a full enumeration from the drive root. A 410
        raises ``DeltaResyncRequired``.

        The stored delta link comes back from response data and the request carries the
        app-only bearer token, so a link outside the configured Graph origin is refused
        rather than followed (credential-scope control); the caller restarts a full
        enumeration, exactly as for an expired link.
        """
        if delta_link and not utils.is_same_origin(delta_link, config.SharePointConfig.GRAPH_BASE_URL):
            raise DeltaResyncRequired(
                f"The stored delta link for drive {drive_id} does not target the configured Graph origin."
            )
        url = delta_link or f"{config.SharePointConfig.GRAPH_BASE_URL}/drives/{drive_id}/root/delta"
        response = self._request_with_retry("GET", url)
        if response.status_code == 410:
            raise DeltaResyncRequired(f"The delta link for drive {drive_id} expired (410 Gone).")
        return response.json()

    def download_item(self, drive_id: str, item_id: str) -> bytes:
        """The content of one drive item."""
        url = f"{config.SharePointConfig.GRAPH_BASE_URL}/drives/{drive_id}/items/{item_id}/content"
        response = self._request_with_retry("GET", url)
        return response.content

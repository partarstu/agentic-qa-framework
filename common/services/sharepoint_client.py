# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Microsoft Graph access for SharePoint document libraries (WS18).

App-only (client-credentials) tokens come from MSAL; the least-privilege setup is the
``Sites.Selected`` application permission granted per site. Graph itself is called over
httpx with explicit timeouts and 429/5xx back-off that honours ``Retry-After``.

Change detection uses delta enumeration on the drive root: the caller pages through
``@odata.nextLink`` to a final ``@odata.deltaLink``; deletions arrive with the ``deleted``
facet; a ``410 Gone`` means the stored delta link expired and a fresh full enumeration is
required.
"""

import time

import httpx
import msal

import config
from common import utils

logger = utils.get_logger("sharepoint_client")

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
# Retries for 429/5xx responses, honouring Retry-After.
MAX_RETRIES = 5
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
        self._authority = f"{config.SharePointConfig.AUTHORITY_URL}/{tenant_id}"
        self._app = msal.ConfidentialClientApplication(
            client_id, authority=self._authority, client_credential=client_secret
        )
        self._token: str | None = None
        self._token_expiry = 0.0

    def _access_token(self) -> str:
        """A cached app-only token, refreshed five minutes before it expires."""
        if self._token is None or time.monotonic() >= self._token_expiry - 300:
            result = self._app.acquire_token_for_client(scopes=[GRAPH_SCOPE])
            if "access_token" not in result:
                raise RuntimeError(f"SharePoint token acquisition failed: {result.get('error_description')}")
            self._token = result["access_token"]
            self._token_expiry = time.monotonic() + int(result.get("expires_in", 3600))
        return self._token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token()}"}

    def _request_with_retry(self, method: str, url: str) -> httpx.Response:
        """One Graph call with 429/5xx back-off that honours Retry-After."""
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            for attempt in range(MAX_RETRIES):
                response = client.request(method, url, headers=self._headers())
                if response.status_code == 410:
                    # The caller must distinguish this from other failures: it changes the
                    # enumeration strategy, it is not a retryable blip.
                    return response
                if response.status_code in (429, 502, 503, 504) and attempt < MAX_RETRIES - 1:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else min(2**attempt, 32)
                    logger.warning(
                        f"Graph {method} {url} returned {response.status_code}; retrying in {delay:.0f}s."
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
        """
        url = delta_link or f"{GRAPH_BASE_URL}/drives/{drive_id}/root/delta"
        response = self._request_with_retry("GET", url)
        if response.status_code == 410:
            raise DeltaResyncRequired(f"The delta link for drive {drive_id} expired (410 Gone).")
        return response.json()

    def download_item(self, drive_id: str, item_id: str) -> bytes:
        """The content of one drive item."""
        url = f"{GRAPH_BASE_URL}/drives/{drive_id}/items/{item_id}/content"
        response = self._request_with_retry("GET", url)
        return response.content

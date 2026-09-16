# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Confluence Cloud REST API v2 client for the document RAG sync (WS9).

Uses basic auth (username + API token), cursor pagination and retries on 429/5xx
responses honouring ``Retry-After``, with explicit timeouts. Only the calls the
ingestion needs are implemented: resolving a space key, listing page metadata
(without bodies), fetching one page's raw storage body and downloading attachments
(WS9b).

Page IDs are strings in the v2 API (they are quoted in the schema), so they stay
strings throughout the sync.
"""

import asyncio

import httpx

import config
from common import utils

logger = utils.get_logger("confluence_client")

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ConfluenceApiError(RuntimeError):
    """A Confluence REST call failed after retries."""


class ConfluenceClient:
    """Minimal Confluence Cloud REST v2 client over the shared httpx stack."""

    def __init__(self) -> None:
        if not config.CONFLUENCE_URL or not config.CONFLUENCE_USERNAME or not config.CONFLUENCE_API_TOKEN:
            raise RuntimeError(
                "Confluence configuration is missing (CONFLUENCE_URL, CONFLUENCE_USERNAME or CONFLUENCE_API_TOKEN)."
            )
        self._base_url = config.CONFLUENCE_URL.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=f"{self._base_url}/wiki/api/v2",
            auth=(config.CONFLUENCE_USERNAME, config.CONFLUENCE_API_TOKEN),
            timeout=config.DocumentRagConfig.CONFLUENCE_TIMEOUT_SECONDS,
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        """GET with retries on 429/5xx, honouring Retry-After."""
        max_retries = config.DocumentRagConfig.CONFLUENCE_MAX_RETRIES
        for attempt in range(max_retries):
            try:
                response = await self._client.get(path, params=params)
            except httpx.TimeoutException as e:
                if attempt == max_retries - 1:
                    raise ConfluenceApiError(f"Confluence request to {path} timed out: {e}") from e
                await asyncio.sleep(min(2**attempt, 30))
                continue
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_retries - 1:
                retry_after = response.headers.get("Retry-After")
                await asyncio.sleep(float(retry_after) if retry_after else min(2**attempt, 30))
                continue
            if response.status_code >= 400:
                raise ConfluenceApiError(f"Confluence request to {path} failed: {response.status_code} {response.text}")
            return response.json()
        raise ConfluenceApiError(f"Confluence request to {path} failed after {max_retries} attempts.")

    async def _get_paginated(self, path: str, params: dict | None = None) -> list[dict]:
        """Collect every result page, following the cursor in ``_links.next``."""
        results: list[dict] = []
        cursor: str | None = None
        while True:
            request_params = dict(params or {})
            if cursor:
                request_params["cursor"] = cursor
            body = await self._get(path, request_params)
            results.extend(body.get("results", []))
            cursor = body.get("_links", {}).get("next")
            if not cursor:
                return results

    async def get_space_id_by_key(self, space_key: str) -> str:
        """Resolves a space key (including personal ``~`` keys) to its space ID."""
        spaces = await self._get_paginated("/spaces", {"keys": [space_key]})
        for space in spaces:
            if space.get("key") == space_key:
                return space["id"]
        raise ConfluenceApiError(f"No Confluence space found for key '{space_key}'.")

    async def list_pages_in_space(self, space_id: str) -> list[dict]:
        """Lists every page of the space, metadata only (id, title, parentId, version, webui)."""
        return await self._get_paginated(
            f"/spaces/{space_id}/pages",
            {"limit": config.DocumentRagConfig.LIST_PAGE_SIZE, "status": ["current"]},
        )

    async def get_page(self, page_id: str) -> dict | None:
        """Fetches one page with its raw storage body, or None when it no longer exists."""
        try:
            return await self._get(f"/pages/{page_id}", {"body-format": "storage"})
        except ConfluenceApiError as e:
            if "404" in str(e):
                return None
            raise

    async def list_page_attachments(self, page_id: str) -> list[dict]:
        """Lists one page's attachments, metadata only (id, title, media type, size,
        version, download link). Filtered to current status; the name pattern is
        applied by the caller, which also knows the skip flags."""
        return await self._get_paginated(
            f"/pages/{page_id}/attachments",
            {
                "limit": config.DocumentRagConfig.LIST_PAGE_SIZE,
                "status": ["current"],
                "sort": "created",
            },
        )

    async def download_attachment(self, download_link: str) -> bytes:
        """Downloads an attachment's bytes through its listed download link.

        The link is relative to the site's ``/wiki`` context path (not to the API base
        URL), but Confluence may already return it with the ``/wiki`` prefix, so the
        prefix is only added when the link doesn't carry it.
        """
        prefixed = download_link if download_link.startswith("/wiki") else f"/wiki{download_link}"
        download_url = f"{self._base_url}{prefixed}"
        max_retries = config.DocumentRagConfig.CONFLUENCE_MAX_RETRIES
        for attempt in range(max_retries):
            try:
                response = await self._client.get(download_url)
            except httpx.TimeoutException as e:
                if attempt == max_retries - 1:
                    raise ConfluenceApiError(f"Attachment download timed out: {e}") from e
                await asyncio.sleep(min(2**attempt, 30))
                continue
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_retries - 1:
                retry_after = response.headers.get("Retry-After")
                await asyncio.sleep(float(retry_after) if retry_after else min(2**attempt, 30))
                continue
            if response.status_code >= 400:
                raise ConfluenceApiError(f"Attachment download failed: {response.status_code}")
            return response.content
        raise ConfluenceApiError("Attachment download failed after retries.")

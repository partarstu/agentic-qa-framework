# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Confluence document ingestion into the documents collection (WS9).

Run algorithm (the fingerprints decide what gets skipped; the cursor is recorded
but doesn't drive skipping, because CQL lastmodified depends on the lagging search
index and misses attachment uploads):

1. List metadata only: pages (id, title, parent, version, web link) and, with WS9b,
   each page's attachments. The attachment name pattern and the skip-page-body
   flag narrow the expected set.
2. Load the scope's stored fingerprints in one read.
3. Classify each item: new, version-changed, unchanged, metadata-only-changed or
   removed. Removal is driven by non-existence in the listing and requires a
   complete listing; a failed listing call deletes nothing.
4. Check 1 - versions: an unchanged version skips without any fetch.
5. Check 2 - raw-content hash plus ingestion-schema version, for new and
   version-changed items only.
6. Process: page body normalize -> chunk -> embed -> upsert.
7. Crash-safe write order: upsert new points, delete leftovers of the previous
   version, save the fingerprint last.
8. Removed items: delete their points and fingerprints; a removed page takes its
   attachments with it.
9. Failure isolation: a failing item is logged and counted, doesn't abort the run
   and doesn't update its fingerprint, so the next run retries it. The run reports
   completed-with-errors and the cursor isn't advanced.

This phase (WS9a) ingests page bodies; attachments ship with WS9b, so the
attachment parts of the algorithm are prepared but empty by default.
"""

import time

import config
from common import utils
from common.models import DocumentPagePart, RagUpdateResult
from common.services.sync_lock_store import SyncLockStore, SyncStateStore, scope_key
from common.services.vector_db_service import VectorDbService
from rag_sync.chunking import chunk_page_body
from rag_sync.confluence_client import ConfluenceApiError, ConfluenceClient
from rag_sync.normalization import normalize_page_body
from rag_sync.sync_state import INGESTION_SCHEMA_VERSION, FingerprintStore, content_hash

logger = utils.get_logger("confluence_sync")

CONFLUENCE_SCOPE = "confluence"


class ConfluenceRagSyncRunner:
    """Runs one Confluence sync for one scope (a space, optionally one page)."""

    def __init__(self) -> None:
        self._documents_db = VectorDbService(
            config.DocumentRagConfig.DOCUMENTS_COLLECTION_NAME,
            metadata_collection_name=config.QdrantConfig.METADATA_COLLECTION_NAME,
        )
        self._metadata_db = VectorDbService(config.QdrantConfig.METADATA_COLLECTION_NAME)
        self._lock_store = SyncLockStore(
            self._metadata_db,
            ttl_seconds=config.RagSyncConfig.LOCK_TTL_SECONDS,
            start_allowance_seconds=config.RagSyncConfig.START_ALLOWANCE_SECONDS,
        )
        self._state_store = SyncStateStore(self._metadata_db)
        self._fingerprints = FingerprintStore(self._metadata_db)

    async def close(self) -> None:
        await self._documents_db.close()
        await self._metadata_db.close()

    async def sync_space(
        self,
        space_key: str,
        page_id: str | None = None,
        attachment_name_pattern: str | None = None,
        skip_page_body: bool = False,
        lock_token: str | None = None,
    ) -> RagUpdateResult:
        """Synchronizes a Confluence space (or one page of it) into the documents collection.

        Args:
            space_key: The Confluence space key (may start with '~' for personal spaces).
            page_id: Restrict the sync to this page of the space.
            attachment_name_pattern: Regex filtering attachment file names (WS9b).
            skip_page_body: Ingest attachments only, skipping page bodies.
            lock_token: The holder token issued by the orchestrator, if any.

        Returns:
            A RagUpdateResult describing the outcome and the number of processed items.

        Raises:
            PermissionError: When the runner no longer holds the lock at a write point.
            RuntimeError: When a tokenless runner cannot acquire the lock.
        """
        scope = scope_key(CONFLUENCE_SCOPE, space_key)
        if lock_token:
            if not await self._lock_store.mark_started(scope, lock_token):
                logger.warning(f"Runner no longer holds the lock for {scope}; aborting without writes.")
                raise PermissionError(f"Lock for scope {scope} was taken over before the run started.")
        else:
            state = await self._lock_store.acquire(scope)
            if not state.acquired:
                raise RuntimeError(f"Another sync already holds the lock for {scope}.")
            lock_token = state.lock_info["holder_token"]

        try:
            return await self._run_sync(
                space_key, scope, lock_token, page_id, attachment_name_pattern, skip_page_body
            )
        finally:
            released = await self._lock_store.release(scope, lock_token)
            if not released:
                logger.warning(f"Lock for {scope} was not released by this runner; it was taken over.")
            await self.close()

    async def _run_sync(
        self,
        space_key: str,
        scope: str,
        lock_token: str,
        page_id: str | None,
        attachment_name_pattern: str | None,
        skip_page_body: bool,
    ) -> RagUpdateResult:
        run_started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        client = ConfluenceClient()
        processed = 0
        failed = 0
        try:
            space_id = await client.get_space_id_by_key(space_key)
            listing_complete, pages = await self._list_pages(client, space_key, space_id, page_id)
            if not listing_complete:
                logger.warning(f"Listing for scope {scope} was incomplete; nothing is deleted this run.")
            stored = await self._fingerprints.load_scope(scope)

            # Classification. Attachments enter the listing with WS9b; until then the
            # expected items are the page bodies only.
            expected: dict[str, dict] = {
                f"page:{page['id']}": page for page in pages
            }

            removed_keys = self._removed_items(stored, expected, listing_complete, scope)

            await self._verify_holder_or_abort(scope, lock_token)
            for item_key, removed_payload in removed_keys.items():
                await self._delete_item(scope, item_key, removed_payload, lock_token)
                processed += 1

            for item_key, page in expected.items():
                if skip_page_body and item_key.startswith("page:"):
                    continue
                try:
                    await self._verify_holder_or_abort(scope, lock_token)
                    if await self._sync_page_body(client, space_key, scope, item_key, page, stored):
                        processed += 1
                except PermissionError:
                    raise
                except Exception as e:
                    failed += 1
                    logger.exception(f"Failed to sync Confluence item {item_key} in {space_key}: {e}")

            status = "completed-with-errors" if failed or not listing_complete else "completed"
            if failed == 0 and listing_complete:
                # The cursor records the last successful run; Confluence doesn't use it
                # for skipping (versions + hashes decide), but the operating model
                # reports it and a reset forces a full re-ingest.
                await self._verify_holder_or_abort(scope, lock_token)
                await self._state_store.save_cursor(
                    scope, {"last_update": run_started, "processed_count": processed}
                )
            return RagUpdateResult(status=status, processed_count=processed)
        finally:
            await client.close()

    async def _list_pages(
        self, client: ConfluenceClient, space_key: str, space_id: str, page_id: str | None
    ) -> tuple[bool, list[dict]]:
        """Lists the scope's pages, metadata only. Returns (listing_complete, pages).

        A page-scoped sync checks the page belongs to the requested space and is
        complete when the page exists.
        """
        try:
            if page_id is None:
                return True, await client.list_pages_in_space(space_id)
            page = await client.get_page(page_id)
            if page is None:
                # The page is gone; a complete empty listing removes all of its items.
                return True, []
            if str(page.get("spaceId")) != str(space_id):
                raise ConfluenceApiError(f"Page {page_id} does not belong to space {space_key}.")
            return True, [page]
        except Exception:
            logger.exception(f"Listing pages for space {space_key} failed; the run will delete nothing.")
            return False, []

    @staticmethod
    def _removed_items(
        stored: dict[str, dict], expected: dict[str, dict], listing_complete: bool, scope: str
    ) -> dict[str, dict]:
        """Stored items missing from the listing, keyed by item key.

        Removal requires a complete listing: an item missing from an incomplete
        listing may still exist, so nothing is removed. Items outside the current
        pattern or skip flag stay untouched - they are not expected in the
        listing-restricted sense, but they remain in ``stored``, so removal only
        triggers when the listing is complete and the item is truly gone.
        """
        if not listing_complete:
            return {}
        removed = {key: payload for key, payload in stored.items() if key not in expected}
        for key in removed:
            logger.info(f"Item {key} of scope {scope} no longer exists; scheduling removal.")
        return removed

    async def _sync_page_body(
        self, client: ConfluenceClient, space_key: str, scope: str, item_key: str, page: dict, stored: dict
    ) -> bool:
        """Syncs one page body. Returns True when the item was processed (changed or new)."""
        stored_fingerprint = stored.get(item_key)
        version = page.get("version", {}).get("number")

        if stored_fingerprint:
            if stored_fingerprint.get("version") == version:
                if self._metadata_changed(stored_fingerprint, page):
                    await self._update_metadata_only(scope, item_key, page, stored_fingerprint)
                    return True
                logger.debug(f"Skipping {item_key} in {space_key}: version unchanged ({version}).")
                return False
            logger.info(f"Version changed for {item_key} in {space_key}: {stored_fingerprint.get('version')} -> {version}.")

        # Check 2: raw-content hash, for new and version-changed items only.
        page_with_body = await client.get_page(page["id"])
        if page_with_body is None:
            logger.info(f"Page {item_key} disappeared before its body was fetched; skipping.")
            return False
        raw_body = page_with_body.get("body", {}).get("storage", {}).get("value", "")
        title = page_with_body.get("title", "")
        hash_value = content_hash(raw_body, title, str(INGESTION_SCHEMA_VERSION))

        if stored_fingerprint and stored_fingerprint.get("content_hash") == hash_value:
            # Equal hash: only the stored version is updated, without re-processing.
            await self._fingerprints.save(scope, item_key, self._fingerprint(page_with_body, hash_value))
            return True

        parts = self._build_page_parts(space_key, page_with_body, raw_body)
        # Crash-safe order: upsert the new points first, then delete the previous
        # version's leftovers (fewer chunks), then save the fingerprint last.
        if parts:
            await self._documents_db.upsert_batch(parts, ensure=True)
        previous = stored_fingerprint.get("point_ids", []) if stored_fingerprint else []
        stale_ids = [pid for pid in previous if pid not in {p.get_vector_id() for p in parts}]
        if stale_ids:
            await self._documents_db.delete(stale_ids)
        await self._fingerprints.save(scope, item_key, self._fingerprint(page_with_body, hash_value, parts))
        logger.info(f"Ingested {len(parts)} chunk(s) of {item_key} in space {space_key}.")
        return True

    @staticmethod
    def _metadata_changed(stored_fingerprint: dict, page: dict) -> bool:
        return (
            stored_fingerprint.get("title") != page.get("title")
            or stored_fingerprint.get("webui") != page.get("_links", {}).get("webui")
        )

    async def _update_metadata_only(
        self, scope: str, item_key: str, page: dict, stored_fingerprint: dict
    ) -> None:
        """A metadata-only change (e.g. the page was renamed) updates the stored
        payload without re-embedding."""
        title = page.get("title", "")
        webui = page.get("_links", {}).get("webui")
        point_ids = stored_fingerprint.get("point_ids", [])
        if point_ids:
            await self._documents_db.set_payload(
                {"page_title": title, "page_url": webui, "document_name": title},
                point_ids=point_ids,
            )
        fingerprint = {
            **stored_fingerprint,
            "title": title,
            "webui": webui,
        }
        await self._fingerprints.save(scope, item_key, fingerprint)
        logger.info(f"Updated metadata of {item_key} in {scope} without re-embedding.")

    @staticmethod
    def _fingerprint(page: dict, hash_value: str, parts: list[DocumentPagePart] | None = None) -> dict:
        fingerprint = {
            "version": page.get("version", {}).get("number"),
            "content_hash": hash_value,
            "schema_version": INGESTION_SCHEMA_VERSION,
            "page_id": page.get("id"),
            "title": page.get("title", ""),
            "webui": page.get("_links", {}).get("webui"),
            "item_kind": "page_body",
        }
        if parts is not None:
            fingerprint["point_ids"] = [part.get_vector_id() for part in parts]
        return fingerprint

    @staticmethod
    def _build_page_parts(space_key: str, page: dict, raw_body: str) -> list[DocumentPagePart]:
        title = page.get("title", "")
        markdown = normalize_page_body(raw_body, title)
        chunks = chunk_page_body(markdown, title)
        webui = page.get("_links", {}).get("webui")
        return [
            DocumentPagePart(
                space_key=space_key,
                page_id=page.get("id"),
                page_title=title,
                page_url=webui,
                content_kind="page_body",
                document_name=title,
                breadcrumb=chunk.breadcrumb,
                text=chunk.content(),
                part_index=chunk.index,
            )
            for chunk in chunks
        ]

    async def _delete_item(self, scope: str, item_key: str, fingerprint: dict, lock_token: str) -> None:
        """Deletes a removed item's points and fingerprint; a removed page takes its
        attachments with it."""
        await self._verify_holder_or_abort(scope, lock_token)
        point_ids = fingerprint.get("point_ids", [])
        if point_ids:
            await self._documents_db.delete(point_ids)
        await self._fingerprints.delete(scope, item_key)
        logger.info(f"Deleted removed item {item_key} of scope {scope} ({len(point_ids)} point(s)).")

    async def _verify_holder_or_abort(self, scope: str, lock_token: str) -> None:
        """Stops at once, without further writes, when the runner no longer holds the lock."""
        if not await self._lock_store.is_holder(scope, lock_token):
            raise PermissionError(f"Lock for scope {scope} was taken over; this run stops without further writes.")

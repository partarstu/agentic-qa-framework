# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Confluence page-body and attachment ingestion into the documents collection.

Run algorithm (the fingerprints decide what gets skipped; the cursor is recorded
but doesn't drive skipping, because CQL lastmodified depends on the lagging search
index and misses attachment uploads):

1. List metadata only: pages (id, title, parent, version, web link) and each page's
   attachments. The attachment name pattern and the skip-page-body flag narrow the
   expected set.
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

"""

import asyncio
import base64
import time
from dataclasses import dataclass

from qdrant_client import models

import config
from common import utils
from common.models import DocumentPagePart, RagUpdateResult, SyncStatus
from common.services.sync_lock_store import SyncLockStore, SyncStateStore, scope_key
from common.services.vector_db_service import VectorDbService
from rag_sync.attachment_extraction import (
    AttachmentSkippedError,
    ExtractedDocument,
    extract_attachment_async,
    skip_reason,
)
from rag_sync.chunking import chunk_page_body, split_text_by_budget
from rag_sync.confluence_client import ConfluenceApiError, ConfluenceClient
from rag_sync.normalization import normalize_page_body
from rag_sync.sync_state import INGESTION_SCHEMA_VERSION, FingerprintStore, content_hash

logger = utils.get_logger("confluence_sync")

CONFLUENCE_SCOPE = "confluence"

# Bounded concurrency for per-page attachment listings: enough to hide per-request
# latency, small enough to stay polite to the Confluence API.
ATTACHMENT_LISTING_CONCURRENCY = 4


@dataclass(frozen=True, slots=True)
class ScopeListing:
    """What one listing pass found: the items to sync, their parent pages and everything that exists."""

    expected: dict[str, dict]
    attachment_pages: dict[str, dict]
    existing_item_keys: set[str]


@dataclass(slots=True)
class ItemCounts:
    """Per-item outcome tally of one run."""

    processed: int = 0
    skipped: int = 0
    failed: int = 0


class ConfluenceRagSyncRunner:
    """Runs one Confluence sync for one scope (a space, optionally one page)."""

    def __init__(self) -> None:
        # One shared metadata service: the documents db records/checks the model identity
        # of its vectors through it, and the lock/state/fingerprint stores write to
        # the same collection.
        self._metadata_db = VectorDbService(config.QdrantConfig.METADATA_COLLECTION_NAME)
        self._documents_db = VectorDbService(
            config.DocumentRagConfig.DOCUMENTS_COLLECTION_NAME,
            metadata_db=self._metadata_db,
        )
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

        Raises:
            PermissionError: When the runner no longer holds the lock at a write point.
            SyncLockHeldError: When a tokenless runner cannot acquire the lock.
        """
        scope = scope_key(CONFLUENCE_SCOPE, space_key)
        try:
            async with self._lock_store.held_for_run(scope, lock_token) as token:
                return await self._run_sync(space_key, scope, token, page_id, attachment_name_pattern, skip_page_body)
        finally:
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
        try:
            space_id = await client.get_space_id_by_key(space_key)
            listing_complete, pages = await self._list_pages(client, space_key, space_id, page_id)
            attachments_complete, page_attachments = await self._list_attachments(client, pages)
            listing_complete = listing_complete and attachments_complete
            if not listing_complete:
                logger.warning("Listing for scope %s was incomplete; nothing is deleted this run.", scope)
            stored = await self._fingerprints.load_scope(scope)
            if await self._has_lost_its_points(space_key, stored):
                stored = await self._reset_fingerprints(scope, stored, lock_token)
            if page_id is not None:
                # Page-scoped run: removal candidates are restricted to the scoped
                # page's items (its body and its attachments); the rest of the space
                # is never touched (reconciliation table).
                stored = {
                    key: payload
                    for key, payload in stored.items()
                    if key == f"page:{page_id}"
                    or (key.startswith("attachment:") and str(payload.get("page_id")) == page_id)
                }

            listing = self._classify_listing(pages, page_attachments, attachment_name_pattern)
            removed_keys = self._removed_items(
                stored, listing.expected, listing_complete, scope, listing.existing_item_keys
            )

            await self._verify_holder_or_abort(scope, lock_token)
            for item_key, removed_payload in removed_keys.items():
                await self._delete_item(scope, item_key, removed_payload, lock_token)
                processed += 1

            counts = await self._process_items(client, space_key, scope, lock_token, listing, stored, skip_page_body)
            processed += counts.processed

            status = SyncStatus.COMPLETED_WITH_ERRORS if counts.failed or not listing_complete else SyncStatus.COMPLETED
            logger.info(
                "Confluence sync of %s finished (%s): %s processed, %s skipped, %s failed.",
                scope,
                status,
                processed,
                counts.skipped,
                counts.failed,
            )
            if counts.failed == 0 and listing_complete:
                # The cursor records the last successful run; Confluence doesn't use it
                # for skipping (versions + hashes decide), but the operating model
                # reports it and a reset forces a full re-ingest.
                await self._verify_holder_or_abort(scope, lock_token)
                await self._state_store.save_cursor(scope, {"last_update": run_started, "processed_count": processed})
            return RagUpdateResult(status=status, processed_count=processed)
        finally:
            await client.close()

    @staticmethod
    def _classify_listing(
        pages: list[dict], page_attachments: dict[str, list[dict]], attachment_name_pattern: str | None
    ) -> ScopeListing:
        """Turns the raw listings into the items this run expects, keyed by item key.

        The name pattern narrows what gets ingested, never what counts as existing: an
        attachment the pattern hides is still present, so reconciliation leaves it alone.
        """
        pattern = utils.compile_name_pattern(attachment_name_pattern) if attachment_name_pattern else None
        page_by_id = {str(page["id"]): page for page in pages}
        expected: dict[str, dict] = {f"page:{page['id']}": page for page in pages}
        attachment_pages: dict[str, dict] = {}
        existing_item_keys = set(expected)
        for page_id, attachments in page_attachments.items():
            for attachment in attachments:
                item_key = f"attachment:{attachment['id']}"
                existing_item_keys.add(item_key)
                if pattern is None or pattern.search(attachment.get("title", "")):
                    expected[item_key] = attachment
                    attachment_pages[item_key] = page_by_id[page_id]
        return ScopeListing(expected=expected, attachment_pages=attachment_pages, existing_item_keys=existing_item_keys)

    async def _process_items(
        self,
        client: ConfluenceClient,
        space_key: str,
        scope: str,
        lock_token: str,
        listing: ScopeListing,
        stored: dict[str, dict],
        skip_page_body: bool,
    ) -> ItemCounts:
        """Syncs every expected item, isolating each item's failure from the rest of the run."""
        counts = ItemCounts()
        for item_key, item in listing.expected.items():
            try:
                await self._verify_holder_or_abort(scope, lock_token)
                if item_key.startswith("attachment:"):
                    # Attachments are never skipped by the skip_page_body flag; the
                    # name pattern already narrowed the expected set.
                    changed = await self._sync_attachment(
                        client,
                        space_key,
                        scope,
                        item_key,
                        item,
                        listing.attachment_pages[item_key],
                        stored,
                        lock_token,
                    )
                else:
                    changed = not skip_page_body and await self._sync_page_body(
                        client, space_key, scope, item_key, item, stored, lock_token
                    )
                if changed:
                    counts.processed += 1
            except PermissionError:
                raise
            except AttachmentSkippedError as skip:
                counts.skipped += 1
                logger.warning("Skipping Confluence item %s in %s: %s", item_key, space_key, skip)
            except Exception as e:
                counts.failed += 1
                logger.exception("Failed to sync Confluence item %s in %s: %s", item_key, space_key, e)
        return counts

    async def _has_lost_its_points(self, space_key: str, stored: dict[str, dict]) -> bool:
        """Whether the space's fingerprints reference points that are no longer in the documents collection.

        The collection is shared by all spaces and recreated when its vector schema or embedding model
        changes, so the check is taken per space. Fingerprints without points (e.g. empty pages)
        cannot tell, so they never trigger a reset.
        """
        if not any(fingerprint.get("point_ids") for fingerprint in stored.values()):
            return False
        space_filter = models.Filter(
            must=[models.FieldCondition(key="space_key", match=models.MatchValue(value=space_key))]
        )
        return not await self._documents_db.has_points(space_filter)

    async def _reset_fingerprints(self, scope: str, stored: dict[str, dict], lock_token: str) -> dict[str, dict]:
        """Forces a full re-ingest of a space whose points are gone from the documents collection.

        The surviving fingerprints would otherwise skip every unchanged item. Returns the now empty
        set of stored fingerprints.
        """
        logger.info("Stored points of %s are missing; resetting its %s fingerprint(s).", scope, len(stored))
        await self._verify_holder_or_abort(scope, lock_token)
        for item_key in stored:
            await self._fingerprints.delete(scope, item_key)
        return {}

    async def _list_attachments(
        self, client: ConfluenceClient, pages: list[dict]
    ) -> tuple[bool, dict[str, list[dict]]]:
        """Lists every page's attachments, metadata only, with bounded concurrency.

        Filtering happens after this complete listing is retained, so an existing
        non-matching attachment is left untouched while a genuinely removed one is
        still reconciled. ANY page's listing failure makes the listing incomplete
        (nothing is deleted this run), while the successful pages' listings are kept.
        """
        semaphore = asyncio.Semaphore(ATTACHMENT_LISTING_CONCURRENCY)

        async def list_one(page: dict) -> tuple[str, list[dict] | None]:
            async with semaphore:
                try:
                    return str(page["id"]), await client.list_page_attachments(page["id"])
                except Exception:
                    logger.exception("Listing attachments of page %s failed; the run will delete nothing.", page["id"])
                    return str(page["id"]), None

        results = await asyncio.gather(*(list_one(page) for page in pages))
        per_page: dict[str, list[dict]] = {}
        listing_complete = True
        for page_id, attachments in results:
            if attachments is None:
                listing_complete = False
            else:
                per_page[page_id] = attachments
        return listing_complete, per_page

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
            logger.exception("Listing pages for space %s failed; the run will delete nothing.", space_key)
            return False, []

    @staticmethod
    def _removed_items(
        stored: dict[str, dict],
        expected: dict[str, dict],
        listing_complete: bool,
        scope: str,
        existing_item_keys: set[str] | None = None,
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
        existing = existing_item_keys if existing_item_keys is not None else set(expected)
        removed = {key: payload for key, payload in stored.items() if key not in existing}
        for key in removed:
            logger.info("Item %s of scope %s no longer exists; scheduling removal.", key, scope)
        return removed

    async def _sync_page_body(
        self,
        client: ConfluenceClient,
        space_key: str,
        scope: str,
        item_key: str,
        page: dict,
        stored: dict,
        lock_token: str,
    ) -> bool:
        """Syncs one page body. Returns True when the item was processed (changed or new)."""
        stored_fingerprint = stored.get(item_key)
        version = page.get("version", {}).get("number")

        if stored_fingerprint:
            if (
                stored_fingerprint.get("version") == version
                and stored_fingerprint.get("schema_version") == INGESTION_SCHEMA_VERSION
            ):
                if self._metadata_changed(stored_fingerprint, page):
                    await self._update_metadata_only(scope, item_key, page, stored_fingerprint, lock_token)
                    return True
                logger.debug("Skipping %s in %s: version unchanged (%s).", item_key, space_key, version)
                return False
            logger.info(
                "Version changed for %s in %s: %s -> %s.",
                item_key,
                space_key,
                stored_fingerprint.get("version"),
                version,
            )

        # Check 2: raw-content hash, for new and version-changed items only. A
        # page-scoped run's listing already fetched the page WITH its body, so it is
        # reused; a space-scoped listing carries no bodies and fetches here.
        page_with_body = (
            page
            if page.get("body", {}).get("storage", {}).get("value") is not None
            else await client.get_page(page["id"])
        )
        if page_with_body is None:
            logger.info("Page %s disappeared before its body was fetched; skipping.", item_key)
            return False
        raw_body = page_with_body.get("body", {}).get("storage", {}).get("value", "")
        title = page_with_body.get("title", "")
        hash_value = content_hash(raw_body, title, str(INGESTION_SCHEMA_VERSION))

        if stored_fingerprint and stored_fingerprint.get("content_hash") == hash_value:
            # Equal hash: only the stored version is updated, without re-processing.
            await self._verify_holder_or_abort(scope, lock_token)
            fingerprint = self._fingerprint(page_with_body, hash_value)
            fingerprint["point_ids"] = stored_fingerprint.get("point_ids", [])
            await self._fingerprints.save(scope, item_key, fingerprint)
            return True

        parts = self._build_page_parts(space_key, page_with_body, raw_body)
        # Crash-safe order: upsert the new points first, then delete the previous
        # version's leftovers (fewer chunks), then save the fingerprint last.
        if parts:
            await self._verify_holder_or_abort(scope, lock_token)
            await self._documents_db.upsert_batch(parts, ensure=True)
        previous = stored_fingerprint.get("point_ids", []) if stored_fingerprint else []
        current_ids = {part.get_vector_id() for part in parts}
        stale_ids = [point_id for point_id in previous if point_id not in current_ids]
        if stale_ids:
            await self._verify_holder_or_abort(scope, lock_token)
            await self._documents_db.delete(stale_ids)
        await self._verify_holder_or_abort(scope, lock_token)
        await self._fingerprints.save(scope, item_key, self._fingerprint(page_with_body, hash_value, parts))
        logger.info("Ingested %s chunk(s) of %s in space %s.", len(parts), item_key, space_key)
        return True

    @staticmethod
    def _metadata_changed(stored_fingerprint: dict, page: dict) -> bool:
        return stored_fingerprint.get("title") != page.get("title") or stored_fingerprint.get("webui") != page.get(
            "_links", {}
        ).get("webui")

    async def _update_metadata_only(
        self,
        scope: str,
        item_key: str,
        page: dict,
        stored_fingerprint: dict,
        lock_token: str,
    ) -> None:
        """A metadata-only change (e.g. the page was renamed) updates the stored
        payload without re-embedding."""
        title = page.get("title", "")
        webui = page.get("_links", {}).get("webui")
        point_ids = stored_fingerprint.get("point_ids", [])
        if point_ids:
            await self._verify_holder_or_abort(scope, lock_token)
            await self._documents_db.set_payload(
                {"page_title": title, "page_url": webui, "document_name": title},
                point_ids=point_ids,
            )
        fingerprint = {
            **stored_fingerprint,
            "title": title,
            "webui": webui,
        }
        await self._verify_holder_or_abort(scope, lock_token)
        await self._fingerprints.save(scope, item_key, fingerprint)
        logger.info("Updated metadata of %s in %s without re-embedding.", item_key, scope)

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
                source=CONFLUENCE_SCOPE,
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

    async def _sync_attachment(
        self,
        client: ConfluenceClient,
        space_key: str,
        scope: str,
        item_key: str,
        attachment: dict,
        parent_page: dict,
        stored: dict,
        lock_token: str,
    ) -> bool:
        """Synchronizes one attachment and returns whether it was processed."""
        stored_fingerprint = stored.get(item_key)
        version = attachment.get("version", {}).get("number")
        if stored_fingerprint:
            if (
                stored_fingerprint.get("version") == version
                and stored_fingerprint.get("schema_version") == INGESTION_SCHEMA_VERSION
            ):
                if self._attachment_metadata_changed(stored_fingerprint, attachment, parent_page):
                    await self._update_attachment_metadata_only(
                        scope,
                        item_key,
                        attachment,
                        parent_page,
                        stored_fingerprint,
                        lock_token,
                    )
                    return True
                logger.debug("Skipping %s in %s: version unchanged (%s).", item_key, space_key, version)
                return False
            logger.info(
                "Version or ingestion schema changed for %s in %s: %s -> %s.",
                item_key,
                space_key,
                stored_fingerprint.get("version"),
                version,
            )

        format_skip_reason = skip_reason(attachment.get("title", ""))
        if format_skip_reason:
            raise AttachmentSkippedError(format_skip_reason)
        listed_size = int(attachment.get("fileSize") or 0)
        if listed_size > config.DocumentRagConfig.MAX_ATTACHMENT_BYTES:
            raise AttachmentSkippedError(
                f"it is {listed_size} bytes, exceeding the {config.DocumentRagConfig.MAX_ATTACHMENT_BYTES}-byte limit"
            )
        download_link = attachment.get("downloadLink")
        if not download_link:
            raise ValueError(f"Attachment {attachment.get('id')} has no download link.")
        content = await client.download_attachment(download_link)
        if len(content) > config.DocumentRagConfig.MAX_ATTACHMENT_BYTES:
            # Same condition as the pre-download check above (reached when Confluence omits or
            # under-reports fileSize), so it is the same skip, not a failure that would keep the
            # run completed-with-errors and re-download the attachment on every following run.
            raise AttachmentSkippedError(
                f"it is {len(content)} bytes once downloaded, exceeding the "
                f"{config.DocumentRagConfig.MAX_ATTACHMENT_BYTES}-byte limit"
            )
        hash_value = content_hash(content, str(INGESTION_SCHEMA_VERSION))

        if stored_fingerprint and stored_fingerprint.get("content_hash") == hash_value:
            if self._attachment_metadata_changed(stored_fingerprint, attachment, parent_page):
                await self._set_attachment_payload_metadata(
                    scope, attachment, parent_page, stored_fingerprint, lock_token
                )
            fingerprint = self._attachment_fingerprint(
                attachment,
                parent_page,
                hash_value,
                point_ids=stored_fingerprint.get("point_ids", []),
            )
            await self._verify_holder_or_abort(scope, lock_token)
            await self._fingerprints.save(scope, item_key, fingerprint)
            return True

        extracted = await extract_attachment_async(attachment.get("title", ""), content)
        parts = self._build_attachment_parts(space_key, parent_page, attachment, extracted)
        if parts:
            await self._verify_holder_or_abort(scope, lock_token)
            await self._documents_db.upsert_batch(parts, ensure=True)
        previous_ids = stored_fingerprint.get("point_ids", []) if stored_fingerprint else []
        current_ids = {part.get_vector_id() for part in parts}
        stale_ids = [point_id for point_id in previous_ids if point_id not in current_ids]
        if stale_ids:
            await self._verify_holder_or_abort(scope, lock_token)
            await self._documents_db.delete(stale_ids)
        await self._verify_holder_or_abort(scope, lock_token)
        await self._fingerprints.save(
            scope,
            item_key,
            self._attachment_fingerprint(
                attachment,
                parent_page,
                hash_value,
                point_ids=[part.get_vector_id() for part in parts],
            ),
        )
        logger.info("Ingested %s part(s) of %s in space %s.", len(parts), item_key, space_key)
        return True

    @staticmethod
    def _attachment_metadata_changed(stored_fingerprint: dict, attachment: dict, parent_page: dict) -> bool:
        return (
            stored_fingerprint.get("page_id") != parent_page.get("id")
            or stored_fingerprint.get("title") != parent_page.get("title")
            or stored_fingerprint.get("webui") != parent_page.get("_links", {}).get("webui")
            or stored_fingerprint.get("attachment_name") != attachment.get("title")
            or stored_fingerprint.get("media_type") != attachment.get("mediaType")
        )

    async def _update_attachment_metadata_only(
        self,
        scope: str,
        item_key: str,
        attachment: dict,
        parent_page: dict,
        stored_fingerprint: dict,
        lock_token: str,
    ) -> None:
        await self._set_attachment_payload_metadata(scope, attachment, parent_page, stored_fingerprint, lock_token)
        fingerprint = self._attachment_fingerprint(
            attachment,
            parent_page,
            stored_fingerprint.get("content_hash", ""),
            point_ids=stored_fingerprint.get("point_ids", []),
        )
        await self._verify_holder_or_abort(scope, lock_token)
        await self._fingerprints.save(scope, item_key, fingerprint)
        logger.info("Updated metadata of %s in %s without re-embedding.", item_key, scope)

    async def _set_attachment_payload_metadata(
        self,
        scope: str,
        attachment: dict,
        parent_page: dict,
        stored_fingerprint: dict,
        lock_token: str,
    ) -> None:
        point_ids = stored_fingerprint.get("point_ids", [])
        if not point_ids:
            return
        await self._verify_holder_or_abort(scope, lock_token)
        await self._documents_db.set_payload(
            {
                "page_id": parent_page.get("id"),
                "page_title": parent_page.get("title", ""),
                "page_url": parent_page.get("_links", {}).get("webui"),
                "attachment_name": attachment.get("title", ""),
                "document_name": attachment.get("title", ""),
                "media_type": attachment.get("mediaType"),
            },
            point_ids=point_ids,
        )

    @staticmethod
    def _attachment_fingerprint(
        attachment: dict,
        parent_page: dict,
        hash_value: str,
        point_ids: list[str],
    ) -> dict:
        return {
            "version": attachment.get("version", {}).get("number"),
            "content_hash": hash_value,
            "schema_version": INGESTION_SCHEMA_VERSION,
            "page_id": parent_page.get("id"),
            "title": parent_page.get("title", ""),
            "webui": parent_page.get("_links", {}).get("webui"),
            "attachment_id": attachment.get("id"),
            "attachment_name": attachment.get("title", ""),
            "media_type": attachment.get("mediaType"),
            "item_kind": "attachment",
            "point_ids": point_ids,
        }

    @staticmethod
    def _build_attachment_parts(
        space_key: str,
        parent_page: dict,
        attachment: dict,
        extracted: ExtractedDocument,
    ) -> list[DocumentPagePart]:
        page_title = parent_page.get("title", "")
        attachment_name = attachment.get("title", "")
        page_url = parent_page.get("_links", {}).get("webui")
        parts: list[DocumentPagePart] = []
        for page_number, page in enumerate(extracted.pages, start=1):
            breadcrumb = f"{page_title} > {attachment_name} > page {page_number} of {extracted.total_page_count}"
            text_parts = split_text_by_budget(page.text, breadcrumb) or [""]
            for part_index, text_part in enumerate(text_parts):
                text = f"{breadcrumb}\n\n{text_part}" if text_part else breadcrumb
                image = None
                if part_index == 0 and page.image is not None:
                    image = base64.b64encode(page.image).decode("ascii")
                parts.append(
                    DocumentPagePart(
                        source=CONFLUENCE_SCOPE,
                        space_key=space_key,
                        page_id=str(parent_page.get("id")),
                        page_title=page_title,
                        page_url=page_url,
                        attachment_id=str(attachment.get("id")),
                        attachment_name=attachment_name,
                        media_type=attachment.get("mediaType"),
                        content_kind="attachment",
                        document_name=attachment_name,
                        breadcrumb=breadcrumb,
                        text=text,
                        page_number=page_number,
                        page_count=extracted.total_page_count,
                        part_index=part_index,
                        image=image,
                    )
                )
        return parts

    async def _delete_item(self, scope: str, item_key: str, fingerprint: dict, lock_token: str) -> None:
        """Deletes a removed item's points and fingerprint; a removed page takes its
        attachments with it."""
        await self._verify_holder_or_abort(scope, lock_token)
        point_ids = fingerprint.get("point_ids", [])
        if point_ids:
            await self._documents_db.delete(point_ids)
        await self._fingerprints.delete(scope, item_key)
        logger.info("Deleted removed item %s of scope %s (%s point(s)).", item_key, scope, len(point_ids))

    async def _verify_holder_or_abort(self, scope: str, lock_token: str) -> None:
        """Stops at once, without further writes, when the runner no longer holds the lock."""
        if not await self._lock_store.is_holder(scope, lock_token):
            raise PermissionError(f"Lock for scope {scope} was taken over; this run stops without further writes.")

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""SharePoint document-library ingestion into the documents collection.

Change detection is delta enumeration on the drive root. A drive-scoped run resumes from
the stored delta link and saves the new one only on a clean run; a folder-scoped run
performs a full delta enumeration filtered to the folder's descendants and does not advance
the drive's delta link (so a later drive run still sees everything). A ``410 Gone`` restarts
a full enumeration and reconciles against stored state.

Files only: folders maintain an id → (name, parent) tree in the sync state from which each
file's ancestor folder ids and folder path are derived. ``cTag`` identifies content changes
and ``eTag`` metadata-only changes (rename/move → payload-only update). A folder rename
triggers a payload-only update of its descendants (delta does not re-report them). Items
with the ``deleted`` facet remove their points and fingerprints; a deleted folder removes
every point carrying its id as an ancestor. Nothing is deleted when the enumeration was
incomplete. Content is processed by the same source-agnostic ingestion pipeline as the
Confluence attachments (format routing, conversion, rendering, OCR, page records, limits,
crash-safe write order, per-item failure isolation).
"""

import asyncio
import base64

import config
from common import utils
from common.models import DocumentPagePart, RagUpdateResult, SyncStatus
from common.services.sharepoint_client import DeltaResyncRequired, SharePointClient
from common.services.sync_lock_store import SyncLockStore, SyncStateStore, scope_key
from common.services.vector_db_service import VectorDbService
from rag_sync.attachment_extraction import (
    AttachmentSkippedError,
    ExtractedDocument,
    extract_attachment_async,
    skip_reason,
)
from rag_sync.chunking import split_text_by_budget
from rag_sync.sync_state import INGESTION_SCHEMA_VERSION, FingerprintStore, content_hash

logger = utils.get_logger("rag_sync")

SHAREPOINT_SCOPE = "sharepoint"
SOURCE = "sharepoint"


class SharePointRagSyncRunner:
    """Runs one SharePoint sync for one drive (optionally one folder) to completion."""

    def __init__(self) -> None:
        self._metadata_db = VectorDbService(config.QdrantConfig.METADATA_COLLECTION_NAME)
        self._documents_db = VectorDbService(
            config.QdrantConfig.SHAREPOINT_COLLECTION_NAME,
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

    async def sync_drive(
        self,
        drive_id: str,
        folder_path: str | None = None,
        file_name_pattern: str | None = None,
        lock_token: str | None = None,
    ) -> RagUpdateResult:
        """Synchronizes one drive — or one folder of it — into the SharePoint collection."""
        scope = scope_key(SHAREPOINT_SCOPE, drive_id)
        try:
            async with self._lock_store.held_for_run(scope, lock_token) as token:
                client = SharePointClient()
                try:
                    return await self._run_sync(client, drive_id, folder_path, file_name_pattern, scope, token)
                finally:
                    client.close()
        finally:
            await self.close()

    async def _run_sync(
        self,
        client: SharePointClient,
        drive_id: str,
        folder_path: str | None,
        file_name_pattern: str | None,
        scope: str,
        lock_token: str,
    ) -> RagUpdateResult:
        logger.info("Starting SharePoint sync for drive %s (folder: %s).", drive_id, folder_path or "root")
        stored = await self._fingerprints.load_scope(scope)
        state = await self._state_store.get_cursor(scope) or {}
        folders: dict[str, dict] = state.get("folders", {})

        folder_scope = bool(folder_path)
        delta_link = None if folder_scope else state.get("delta_link")
        items, new_folders, new_delta_link, full_enumeration = await self._enumerate(client, drive_id, delta_link)
        renamed_folder_ids = {
            folder_id
            for folder_id, folder in new_folders.items()
            if folder_id in folders and folders[folder_id] != folder
        }
        folders = {**folders, **new_folders}
        for item in items:
            if self._is_deleted(item):
                folders.pop(item["id"], None)
        # Taken before any filter: reconciliation must never delete a file only a filter hid.
        listed_ids = {item["id"] for item in items if self._is_file(item)}

        scope_folder_id = None
        if folder_scope:
            scope_folder_id = self._resolve_folder_id(folders, drive_id, folder_path)
            if scope_folder_id is None:
                logger.warning("Folder %r not found in drive %s; nothing to sync.", folder_path, drive_id)
                return RagUpdateResult(status=SyncStatus.COMPLETED, processed_count=0)
            items = [
                item for item in items if self._is_file(item) and scope_folder_id in self._ancestor_ids(item, folders)
            ]

        if file_name_pattern:
            pattern = utils.compile_name_pattern(file_name_pattern)
            items = [item for item in items if self._is_deleted(item) or pattern.search(item.get("name", ""))]

        # Delta doesn't re-report the descendants of a renamed or moved folder, so their payloads are
        # refreshed from the stored fingerprints.
        for item_key, fingerprint in list(stored.items()):
            if renamed_folder_ids.intersection(fingerprint.get("ancestor_ids", [])):
                stored[item_key] = await self._update_payload_metadata(
                    scope, _item_from_fingerprint(fingerprint), folders, fingerprint, lock_token
                )

        processed = skipped = failed = deleted = 0
        for item in items:
            if self._is_deleted(item):
                deleted += await self._delete_item_tree(scope, item, stored, lock_token)
                continue
            if not self._is_file(item):
                continue
            await self._verify_holder_or_abort(scope, lock_token)
            try:
                if await self._sync_file(client, drive_id, item, folders, stored, scope, lock_token):
                    processed += 1
            except PermissionError:
                raise
            except AttachmentSkippedError as skip:
                skipped += 1
                logger.warning("Skipping SharePoint item %s in drive %s: %s", item["id"], drive_id, skip)
            except Exception as e:
                failed += 1
                logger.exception("Failed to sync SharePoint item %s in drive %s: %s", item["id"], drive_id, e)

        # Reconciliation deletes what a complete full enumeration of the whole drive proves gone;
        # an incremental delta or a folder-scoped run cannot know that.
        if full_enumeration and not folder_scope and new_delta_link:
            for item_key, fingerprint in list(stored.items()):
                if fingerprint.get("item_id") not in listed_ids:
                    await self._delete_points(scope, item_key, fingerprint, lock_token)
                    deleted += 1
        elif folder_scope:
            logger.debug("Folder-scoped run: deletions are left to the next drive-wide run.")
        elif not full_enumeration:
            logger.debug("Incremental delta run: deletions need a full enumeration.")
        else:
            logger.warning("Delta enumeration did not complete; skipping deletions for this run.")

        # The delta link advances only on a clean drive-scoped run: after a failure the next run must see
        # the failed files again, and a folder-scoped run must leave everything it filtered away to the
        # next drive run.
        advance = new_delta_link and not folder_scope and failed == 0
        saved_delta_link = new_delta_link if advance else state.get("delta_link")
        await self._state_store.save_cursor(scope, {"delta_link": saved_delta_link, "folders": folders})

        status = SyncStatus.COMPLETED_WITH_ERRORS if failed else SyncStatus.COMPLETED
        logger.info(
            "SharePoint sync for drive %s finished (%s): %s processed, %s skipped, %s failed, %s deleted.",
            drive_id,
            status,
            processed,
            skipped,
            failed,
            deleted,
        )
        return RagUpdateResult(status=status, processed_count=processed)

    async def _enumerate(
        self, client: SharePointClient, drive_id: str, delta_link: str | None
    ) -> tuple[list[dict], dict[str, dict], str | None, bool]:
        """Pages through the delta enumeration.

        Returns (items, folder tree updates, the final delta link, whether the successful
        chain enumerated from the root). A ``410 Gone`` restarts a full enumeration, so the
        caller may reconcile its deletions against stored state.
        """
        items: list[dict] = []
        folders: dict[str, dict] = {}
        link = delta_link
        full = link is None
        while True:
            try:
                page = await asyncio.to_thread(client.enumerate_delta, drive_id, link)
            except DeltaResyncRequired as resync:
                if link is None:
                    raise
                logger.warning("Stored SharePoint delta link unusable (%s); restarting a full enumeration.", resync)
                items, folders = [], {}
                link = None
                full = True
                continue
            for item in page.get("value", []):
                # A deleted folder is an item to delete, not part of the folder tree.
                if self._is_folder(item) and not self._is_deleted(item):
                    folders[item["id"]] = {
                        "name": item.get("name", ""),
                        "parent": item.get("parentReference", {}).get("id"),
                    }
                else:
                    items.append(item)
            if link := page.get("@odata.nextLink"):
                continue
            return items, folders, page.get("@odata.deltaLink"), full

    @staticmethod
    def _is_folder(item: dict) -> bool:
        return "folder" in item

    @staticmethod
    def _is_file(item: dict) -> bool:
        return "file" in item and "deleted" not in item

    @staticmethod
    def _is_deleted(item: dict) -> bool:
        return "deleted" in item

    def _ancestor_ids(self, item: dict, folders: dict[str, dict]) -> list[str]:
        """The ancestor folder ids of an item, nearest first, from the folder tree."""
        ancestors: list[str] = []
        parent = (item.get("parentReference") or {}).get("id")
        while parent and parent not in ancestors:
            ancestors.append(parent)
            parent = folders.get(parent, {}).get("parent")
        return ancestors

    def _folder_path(self, item: dict, folders: dict[str, dict]) -> str:
        """The slash-joined path of an item's ancestors, root first."""
        names = [
            folders.get(folder_id, {}).get("name", "") for folder_id in reversed(self._ancestor_ids(item, folders))
        ]
        return "/".join(name for name in names if name)

    def _resolve_folder_id(self, folders: dict[str, dict], drive_id: str, folder_path: str) -> str | None:
        """The folder id matching the requested path, matched on the slash-joined names."""
        wanted = [segment for segment in folder_path.strip("/").split("/") if segment]
        for folder_id in folders:
            chain: list[str] = []
            parent: str | None = folder_id
            while parent:
                chain.insert(0, folders.get(parent, {}).get("name", ""))
                parent = folders.get(parent, {}).get("parent")
            if [segment for segment in chain if segment] == wanted:
                return folder_id
        return None

    async def _sync_file(
        self,
        client: SharePointClient,
        drive_id: str,
        item: dict,
        folders: dict[str, dict],
        stored: dict[str, dict],
        scope: str,
        lock_token: str,
    ) -> bool:
        """Synchronizes one file: skip, payload-only update or full ingest (cTag/eTag rules)."""
        item_key = f"file:{item['id']}"
        name = item.get("name", "")
        stored_fingerprint = stored.get(item_key)
        if stored_fingerprint:
            renamed_or_moved = stored_fingerprint.get("name") != name or stored_fingerprint.get(
                "folder_path"
            ) != self._folder_path(item, folders)
            if stored_fingerprint.get("ctag") == item.get("cTag"):
                # The content is unchanged: a rename or move is a payload-only update.
                if renamed_or_moved:
                    stored[item_key] = await self._update_payload_metadata(
                        scope, item, folders, stored_fingerprint, lock_token
                    )
                else:
                    logger.debug("Skipping %s: cTag unchanged.", item_key)
                return False

        format_skip_reason = skip_reason(name)
        if format_skip_reason:
            raise AttachmentSkippedError(f"{item_key} ({name}): {format_skip_reason}")
        size = int(item.get("size") or 0)
        if size > config.DocumentRagConfig.MAX_ATTACHMENT_BYTES:
            raise AttachmentSkippedError(
                f"{item_key} ({name}) is {size} bytes, exceeding the {config.DocumentRagConfig.MAX_ATTACHMENT_BYTES}-byte limit"
            )
        content = await asyncio.to_thread(client.download_item, drive_id, item["id"])
        if len(content) > config.DocumentRagConfig.MAX_ATTACHMENT_BYTES:
            # Same condition as the pre-download check above (reached when the listed size is
            # missing or wrong), so it is the same skip, not a failure that would keep the run
            # completed-with-errors and re-download the file on every following run.
            raise AttachmentSkippedError(
                f"{item_key} ({name}) is {len(content)} bytes once downloaded, exceeding the "
                f"{config.DocumentRagConfig.MAX_ATTACHMENT_BYTES}-byte limit"
            )
        hash_value = content_hash(content, str(INGESTION_SCHEMA_VERSION))
        if stored_fingerprint and stored_fingerprint.get("content_hash") == hash_value:
            fingerprint = self._fingerprint(
                item, folders, hash_value, point_ids=stored_fingerprint.get("point_ids", [])
            )
            await self._verify_holder_or_abort(scope, lock_token)
            await self._fingerprints.save(scope, item_key, fingerprint)
            return True

        extracted = await extract_attachment_async(name, content)
        parts = self._build_parts(item, folders, extracted)
        await self._verify_holder_or_abort(scope, lock_token)
        if parts:
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
            self._fingerprint(item, folders, hash_value, point_ids=[part.get_vector_id() for part in parts]),
        )
        logger.info("Ingested %s part(s) of %s (%s).", len(parts), item_key, name)
        return True

    def _fingerprint(self, item: dict, folders: dict[str, dict], hash_value: str, point_ids: list[str]) -> dict:
        return {
            "item_id": item["id"],
            "name": item.get("name", ""),
            "ctag": item.get("cTag"),
            "etag": item.get("eTag"),
            "folder_path": self._folder_path(item, folders),
            "ancestor_ids": self._ancestor_ids(item, folders),
            "content_hash": hash_value,
            "schema_version": INGESTION_SCHEMA_VERSION,
            "point_ids": point_ids,
        }

    def _build_parts(
        self, item: dict, folders: dict[str, dict], extracted: ExtractedDocument
    ) -> list[DocumentPagePart]:
        name = item.get("name", "")
        folder_path = self._folder_path(item, folders)
        parts: list[DocumentPagePart] = []
        for page_number, page in enumerate(extracted.pages, start=1):
            breadcrumb = (
                f"{folder_path + '/' if folder_path else ''}{name} > page {page_number} of {extracted.total_page_count}"
            )
            text_parts = split_text_by_budget(page.text, breadcrumb) or [""]
            for part_index, text_part in enumerate(text_parts):
                text = f"{breadcrumb}\n\n{text_part}" if text_part else breadcrumb
                image = None
                if part_index == 0 and page.image is not None:
                    image = base64.b64encode(page.image).decode("ascii")
                parts.append(
                    DocumentPagePart(
                        source=SOURCE,
                        space_key="",
                        page_id=str(item["id"]),
                        page_title=name,
                        drive_id=str((item.get("parentReference") or {}).get("driveId", "")),
                        folder_path=folder_path,
                        attachment_id=str(item["id"]),
                        attachment_name=name,
                        media_type=item.get("file", {}).get("mimeType"),
                        content_kind="attachment",
                        document_name=name,
                        breadcrumb=breadcrumb,
                        text=text,
                        page_number=page_number,
                        page_count=extracted.total_page_count,
                        part_index=part_index,
                        image=image,
                    )
                )
        return parts

    async def _update_payload_metadata(
        self, scope: str, item: dict, folders: dict[str, dict], stored_fingerprint: dict, lock_token: str
    ) -> dict:
        """A rename/move or a folder rename: refresh the payload fields without re-embedding."""
        name = item.get("name", "")
        folder_path = self._folder_path(item, folders)
        await self._verify_holder_or_abort(scope, lock_token)
        await self._documents_db.set_payload(
            {
                "page_title": name,
                "attachment_name": name,
                "document_name": name,
                "folder_path": folder_path,
                "breadcrumb": f"{folder_path + '/' if folder_path else ''}{name}",
            },
            point_ids=stored_fingerprint.get("point_ids", []),
        )
        fingerprint = {
            **stored_fingerprint,
            "name": name,
            "folder_path": folder_path,
            "ancestor_ids": self._ancestor_ids(item, folders),
            "etag": item.get("eTag"),
        }
        await self._fingerprints.save(scope, f"file:{item['id']}", fingerprint)
        logger.info("Payload-only update of %s (%s point(s)).", name, len(stored_fingerprint.get("point_ids", [])))
        return fingerprint

    async def _delete_item_tree(self, scope: str, item: dict, stored: dict[str, dict], lock_token: str) -> int:
        """Deletes a deleted item's points and fingerprint; a deleted folder takes every
        point carrying its id as an ancestor with it."""
        deleted = 0
        for item_key, fingerprint in list(stored.items()):
            if fingerprint.get("item_id") == item["id"] or item["id"] in fingerprint.get("ancestor_ids", []):
                await self._delete_points(scope, item_key, fingerprint, lock_token)
                del stored[item_key]
                deleted += 1
        return deleted

    async def _delete_points(self, scope: str, item_key: str, fingerprint: dict, lock_token: str) -> None:
        await self._verify_holder_or_abort(scope, lock_token)
        point_ids = fingerprint.get("point_ids", [])
        if point_ids:
            await self._documents_db.delete(point_ids)
        await self._fingerprints.delete(scope, item_key)
        logger.info("Deleted removed SharePoint item %s (%s point(s)).", item_key, len(point_ids))

    async def _verify_holder_or_abort(self, scope: str, lock_token: str) -> None:
        """Stops at once, without further writes, when the runner no longer holds the lock."""
        if not await self._lock_store.is_holder(scope, lock_token):
            raise PermissionError(f"Lock for scope {scope} was taken over; this run stops without further writes.")


def _item_from_fingerprint(fingerprint: dict) -> dict:
    """The drive-item fields a payload-only update reads, rebuilt from a stored fingerprint for a file
    the delta did not report (the descendant of a renamed folder)."""
    ancestor_ids = fingerprint.get("ancestor_ids") or []
    return {
        "id": fingerprint["item_id"],
        "name": fingerprint.get("name", ""),
        "eTag": fingerprint.get("etag"),
        "parentReference": {"id": ancestor_ids[0]} if ancestor_ids else {},
    }

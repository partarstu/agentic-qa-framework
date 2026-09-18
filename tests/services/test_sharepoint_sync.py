# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the SharePoint document-library ingestion (WS18).

Every external boundary (Microsoft Graph, Qdrant) is mocked; the tests assert the delta
paging, the 410 resync, folder-tree scoping, the cTag/eTag classification and the deletion
guards.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# The Docker image copies services/rag_sync/ to /app/rag_sync (flat layout); mirror it
# for the tests by putting services/ on the path (rag_sync is a namespace package).
SERVICES_DIR = Path(__file__).resolve().parents[2] / "services"
if str(SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICES_DIR))

from rag_sync.sharepoint_sync import SharePointRagSyncRunner  # noqa: E402

from common.services.sharepoint_client import DeltaResyncRequired  # noqa: E402

DRIVE_ID = "drive-1"


def _file(item_id: str, name: str, parent_id: str, **extra) -> dict:
    return {
        "id": item_id,
        "name": name,
        "file": {"mimeType": "application/pdf"},
        "size": 100,
        "cTag": f"c-{item_id}",
        "eTag": f"e-{item_id}",
        "parentReference": {"id": parent_id, "driveId": DRIVE_ID},
        **extra,
    }


def _folder(item_id: str, name: str, parent_id: str | None) -> dict:
    return {
        "id": item_id,
        "name": name,
        "folder": {"childCount": 0},
        "parentReference": {"id": parent_id, "driveId": DRIVE_ID} if parent_id else {"driveId": DRIVE_ID},
    }


def _deleted(item: dict) -> dict:
    deleted = dict(item)
    deleted["deleted"] = {"state": "deleted"}
    # A delta tombstone carries the deleted facet and minimal metadata, no type facets.
    deleted.pop("file", None)
    deleted.pop("folder", None)
    return deleted


@pytest.fixture
def graph():
    client = MagicMock()
    client.enumerate_delta = MagicMock(return_value={"value": [], "@odata.deltaLink": "https://graph/delta"})
    client.download_item = MagicMock(return_value=b"content")
    return client


@pytest.fixture
def runner(graph):
    documents_db = MagicMock()
    documents_db.close = AsyncMock()
    documents_db.upsert_batch = AsyncMock()
    documents_db.delete = AsyncMock()
    documents_db.set_payload = AsyncMock()
    documents_db.ensure_collection = AsyncMock()
    documents_db.client = AsyncMock()
    documents_db.client.scroll.return_value = ([], None)
    metadata_db = MagicMock()
    metadata_db.close = AsyncMock()
    lock_store = MagicMock()
    lock_store.acquire = AsyncMock(return_value=MagicMock(acquired=True, lock_info={"holder_token": "t"}))
    lock_store.mark_started = AsyncMock(return_value=True)
    lock_store.is_holder = AsyncMock(return_value=True)
    lock_store.release = AsyncMock(return_value=True)
    state_store = MagicMock()
    state_store.get_cursor = AsyncMock(return_value=None)
    state_store.save_cursor = AsyncMock()
    fingerprint_store = MagicMock()
    fingerprint_store.load_scope = AsyncMock(return_value={})
    fingerprint_store.save = AsyncMock()
    fingerprint_store.delete = AsyncMock()
    with (
        patch("rag_sync.sharepoint_sync.VectorDbService", side_effect=[metadata_db, documents_db]),
        patch("rag_sync.sharepoint_sync.SyncLockStore", return_value=lock_store),
        patch("rag_sync.sharepoint_sync.SyncStateStore", return_value=state_store),
        patch("rag_sync.sharepoint_sync.FingerprintStore", return_value=fingerprint_store),
        patch("rag_sync.sharepoint_sync.SharePointClient", return_value=graph),
        patch("rag_sync.sharepoint_sync.extract_attachment_async", new_callable=AsyncMock) as mock_extract,
    ):
        from rag_sync.attachment_extraction import ExtractedDocument, PageContent

        mock_extract.return_value = ExtractedDocument(
            pages=[PageContent(text="extracted text", image=b"png")], total_page_count=1
        )
        runner = SharePointRagSyncRunner()
        runner._graph = graph
        runner._documents_db = documents_db
        runner._lock_store = lock_store
        runner._state_store = state_store
        runner._fingerprints = fingerprint_store
        yield runner


class TestDeltaPaging:
    @pytest.mark.asyncio
    async def test_a_drive_run_resumes_from_the_stored_delta_link(self, runner, graph):
        runner._state_store.get_cursor.return_value = {"delta_link": "https://graph/stored-delta", "folders": {}}

        await runner.sync_drive(DRIVE_ID)

        assert graph.enumerate_delta.call_args_list[0].args[1] == "https://graph/stored-delta"

    @pytest.mark.asyncio
    async def test_a_clean_drive_run_saves_the_new_delta_link(self, runner):
        runner._graph.enumerate_delta.return_value = {"value": [], "@odata.deltaLink": "https://graph/new-delta"}

        await runner.sync_drive(DRIVE_ID)

        saved = runner._state_store.save_cursor.await_args.args[1]
        assert saved["delta_link"] == "https://graph/new-delta"

    @pytest.mark.asyncio
    async def test_a_folder_run_does_not_advance_the_drive_delta_link(self, runner, graph):
        runner._state_store.get_cursor.return_value = {"delta_link": "https://graph/stored-delta", "folders": {}}
        root = _folder("root", "", None)
        docs = _folder("f-docs", "Docs", "root")
        graph.enumerate_delta.return_value = {
            "value": [root, docs, _file("i-1", "spec.pdf", "f-docs")],
            "@odata.deltaLink": "https://graph/new-delta",
        }

        await runner.sync_drive(DRIVE_ID, folder_path="Docs")

        saved = runner._state_store.save_cursor.await_args.args[1]
        assert saved["delta_link"] == "https://graph/stored-delta"

    @pytest.mark.asyncio
    async def test_an_incomplete_enumeration_never_deletes(self, runner, graph):
        runner._state_store.get_cursor.return_value = {"delta_link": "https://graph/stored-delta", "folders": {}}
        # The enumeration ends without a delta link: incomplete, so nothing may be deleted.
        pages = [
            {"value": [], "@odata.nextLink": "https://graph/next"},
            {"value": []},
        ]
        graph.enumerate_delta = MagicMock(side_effect=lambda drive_id, link=None: pages.pop(0))
        runner._fingerprints.load_scope.return_value = {
            "file:i-gone": {"item_id": "i-gone", "point_ids": ["p1"], "ancestor_ids": []}
        }

        await runner.sync_drive(DRIVE_ID)

        runner._documents_db.delete.assert_not_awaited()
        runner._fingerprints.delete.assert_not_awaited()


class TestResyncOn410:
    @pytest.mark.asyncio
    async def test_a_410_restarts_a_full_enumeration_and_reconciles(self, runner, graph):
        runner._state_store.get_cursor.return_value = {"delta_link": "https://graph/stale", "folders": {}}
        responses = [
            DeltaResyncRequired("expired"),
            {"value": [_file("i-1", "kept.pdf", "root")], "@odata.deltaLink": "https://graph/new-delta"},
        ]

        def enumerate_delta(drive_id, link=None):
            outcome = responses.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        graph.enumerate_delta = MagicMock(side_effect=enumerate_delta)
        runner._fingerprints.load_scope.return_value = {
            "file:i-gone": {"item_id": "i-gone", "point_ids": ["p-gone"], "ancestor_ids": []}
        }

        await runner.sync_drive(DRIVE_ID)

        # The second call restarted from the root (no delta link).
        assert graph.enumerate_delta.call_args_list[1].args[1] is None
        # The vanished file's points and fingerprint are gone.
        runner._documents_db.delete.assert_awaited_once_with(["p-gone"])
        runner._fingerprints.delete.assert_awaited_once_with("sharepoint:drive-1", "file:i-gone")


class TestFolderScoping:
    @pytest.mark.asyncio
    async def test_a_folder_run_syncs_only_the_folder_descendants(self, runner, graph):
        root = _folder("root", "", None)
        docs = _folder("f-docs", "Docs", "root")
        other = _folder("f-other", "Other", "root")
        graph.enumerate_delta.return_value = {
            "value": [
                root,
                docs,
                other,
                _file("i-in", "inside.pdf", "f-docs"),
                _file("i-out", "outside.pdf", "f-other"),
            ],
            "@odata.deltaLink": "https://graph/delta",
        }

        result = await runner.sync_drive(DRIVE_ID, folder_path="Docs")

        assert result.processed_count == 1
        ingested = [part for batch in runner._documents_db.upsert_batch.await_args_list for part in batch.args[0]]
        assert {part.attachment_id for part in ingested} == {"i-in"}


class TestCtagEtagClassification:
    def _stored(self, item, point_ids=None, **overrides):
        fingerprint = {
            "item_id": item["id"],
            "name": item["name"],
            "ctag": item.get("cTag"),
            "etag": item.get("eTag"),
            "folder_path": "Docs",
            "ancestor_ids": ["f-docs"],
            "content_hash": "h",
            "schema_version": 1,
            "point_ids": point_ids or [],
        }
        fingerprint.update(overrides)
        return fingerprint

    @pytest.mark.asyncio
    async def test_an_unchanged_file_is_skipped(self, runner, graph):
        item = _file("i-1", "spec.pdf", "f-docs")
        graph.enumerate_delta.return_value = {
            "value": [_folder("root", "", None), _folder("f-docs", "Docs", "root"), item],
            "@odata.deltaLink": "d",
        }
        runner._fingerprints.load_scope.return_value = {"file:i-1": self._stored(item)}

        processed = await runner.sync_drive(DRIVE_ID)

        assert processed.processed_count == 0
        runner._documents_db.upsert_batch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_rename_without_a_content_change_is_a_payload_only_update(self, runner, graph):
        item = _file("i-1", "renamed.pdf", "f-docs")
        stored = self._stored(item, point_ids=["p1", "p2"])
        stored["name"] = "old.pdf"
        graph.enumerate_delta.return_value = {
            "value": [_folder("root", "", None), _folder("f-docs", "Docs", "root"), item],
            "@odata.deltaLink": "d",
        }
        runner._fingerprints.load_scope.return_value = {"file:i-1": stored}

        await runner.sync_drive(DRIVE_ID)

        runner._documents_db.upsert_batch.assert_not_awaited()
        runner._documents_db.set_payload.assert_awaited_once()
        payload = runner._documents_db.set_payload.await_args.args[0]
        assert payload["document_name"] == "renamed.pdf"

    @pytest.mark.asyncio
    async def test_a_content_change_reingests_the_file(self, runner, graph):
        item = _file("i-1", "spec.pdf", "f-docs")
        stored = self._stored(item, point_ids=["p-old"])
        stored["ctag"] = "c-old"
        graph.enumerate_delta.return_value = {
            "value": [_folder("root", "", None), _folder("f-docs", "Docs", "root"), item],
            "@odata.deltaLink": "d",
        }
        runner._fingerprints.load_scope.return_value = {"file:i-1": stored}

        await runner.sync_drive(DRIVE_ID)

        assert runner._documents_db.upsert_batch.await_count >= 1
        # The previous content's points are replaced.
        runner._documents_db.delete.assert_awaited_once_with(["p-old"])


class TestDeletions:
    @pytest.mark.asyncio
    async def test_a_deleted_file_loses_its_points_and_fingerprint(self, runner, graph):
        item = _deleted(_file("i-1", "gone.pdf", "root"))
        graph.enumerate_delta.return_value = {"value": [_folder("root", "", None), item], "@odata.deltaLink": "d"}
        runner._fingerprints.load_scope.return_value = {
            "file:i-1": {"item_id": "i-1", "point_ids": ["p1"], "ancestor_ids": []}
        }

        await runner.sync_drive(DRIVE_ID)

        runner._documents_db.delete.assert_awaited_once_with(["p1"])
        runner._fingerprints.delete.assert_awaited_once_with("sharepoint:drive-1", "file:i-1")

    @pytest.mark.asyncio
    async def test_a_deleted_folder_takes_its_descendants_with_it(self, runner, graph):
        # An incremental delta: only the change (the deleted folder) is reported, so the
        # deletion comes from the deleted facet, not from reconciliation.
        runner._state_store.get_cursor.return_value = {"delta_link": "https://graph/stored-delta", "folders": {}}
        deleted_folder = _deleted(_folder("f-docs", "Docs", "root"))
        graph.enumerate_delta.return_value = {
            "value": [_folder("root", "", None), deleted_folder],
            "@odata.deltaLink": "d",
        }
        runner._fingerprints.load_scope.return_value = {
            "file:i-in": {"item_id": "i-in", "point_ids": ["p-in"], "ancestor_ids": ["f-docs"]},
            "file:i-out": {"item_id": "i-out", "point_ids": ["p-out"], "ancestor_ids": ["f-other"]},
        }

        await runner.sync_drive(DRIVE_ID)

        runner._documents_db.delete.assert_awaited_once_with(["p-in"])
        runner._fingerprints.delete.assert_awaited_once_with("sharepoint:drive-1", "file:i-in")


class TestSizeCap:
    @pytest.mark.asyncio
    async def test_an_oversized_file_is_rejected_before_download(self, runner, graph):
        with patch("config.DocumentRagConfig.MAX_ATTACHMENT_BYTES", 10):
            item = _file("i-big", "huge.pdf", "root", size=99999)
            graph.enumerate_delta.return_value = {"value": [_folder("root", "", None), item], "@odata.deltaLink": "d"}

            result = await runner.sync_drive(DRIVE_ID)

        # A skip is isolated to its file and does not mark the run as failed.
        assert result.status == "completed"
        graph.download_item.assert_not_called()


class TestFailureIsolation:
    @pytest.mark.asyncio
    async def test_a_failing_file_does_not_stop_the_others_and_keeps_the_delta_link(self, runner, graph):
        runner._state_store.get_cursor.return_value = {"delta_link": "https://graph/stored-delta", "folders": {}}
        graph.enumerate_delta.return_value = {
            "value": [_folder("root", "", None), _file("i-bad", "bad.pdf", "root"), _file("i-ok", "ok.pdf", "root")],
            "@odata.deltaLink": "https://graph/new-delta",
        }
        graph.download_item.side_effect = [RuntimeError("download failed"), b"content"]

        result = await runner.sync_drive(DRIVE_ID)

        assert (result.status, result.processed_count) == ("completed-with-errors", 1)
        # The next run must see the failed file again, so the delta link does not advance.
        saved = runner._state_store.save_cursor.await_args.args[1]
        assert saved["delta_link"] == "https://graph/stored-delta"


class TestReconciliation:
    @pytest.mark.asyncio
    async def test_a_file_name_pattern_never_deletes_the_files_it_filters_out(self, runner, graph):
        graph.enumerate_delta.return_value = {
            "value": [
                _folder("root", "", None),
                _file("i-spec", "spec.pdf", "root"),
                _file("i-notes", "notes.pdf", "root"),
            ],
            "@odata.deltaLink": "d",
        }
        runner._fingerprints.load_scope.return_value = {
            "file:i-notes": {"item_id": "i-notes", "point_ids": ["p-notes"], "ancestor_ids": ["root"]},
            "file:i-gone": {"item_id": "i-gone", "point_ids": ["p-gone"], "ancestor_ids": ["root"]},
        }

        await runner.sync_drive(DRIVE_ID, file_name_pattern=r"^spec")

        # Only the file missing from the complete enumeration is deleted.
        runner._documents_db.delete.assert_awaited_once_with(["p-gone"])

    @pytest.mark.asyncio
    async def test_a_deleted_folder_reported_with_its_folder_facet_is_deleted(self, runner, graph):
        runner._state_store.get_cursor.return_value = {
            "delta_link": "https://graph/stored-delta",
            "folders": {"f-docs": {"name": "Docs", "parent": "root"}},
        }
        deleted_folder = {**_folder("f-docs", "Docs", "root"), "deleted": {"state": "deleted"}}
        graph.enumerate_delta.return_value = {"value": [deleted_folder], "@odata.deltaLink": "d"}
        runner._fingerprints.load_scope.return_value = {
            "file:i-in": {"item_id": "i-in", "point_ids": ["p-in"], "ancestor_ids": ["f-docs"]},
        }

        await runner.sync_drive(DRIVE_ID)

        runner._documents_db.delete.assert_awaited_once_with(["p-in"])
        saved_folders = runner._state_store.save_cursor.await_args.args[1]["folders"]
        assert "f-docs" not in saved_folders


class TestFolderRename:
    @pytest.mark.asyncio
    async def test_a_folder_rename_refreshes_the_payload_of_its_unreported_descendants(self, runner, graph):
        runner._state_store.get_cursor.return_value = {
            "delta_link": "https://graph/stored-delta",
            "folders": {"root": {"name": "", "parent": None}, "f-docs": {"name": "Docs", "parent": "root"}},
        }
        graph.enumerate_delta.return_value = {"value": [_folder("f-docs", "Specs", "root")], "@odata.deltaLink": "d"}
        runner._fingerprints.load_scope.return_value = {
            "file:i-1": {
                "item_id": "i-1",
                "name": "spec.pdf",
                "folder_path": "Docs",
                "ancestor_ids": ["f-docs", "root"],
                "point_ids": ["p1"],
            },
        }

        await runner.sync_drive(DRIVE_ID)

        payload = runner._documents_db.set_payload.await_args.args[0]
        assert payload["folder_path"] == "Specs"
        assert runner._documents_db.set_payload.await_args.kwargs["point_ids"] == ["p1"]
        saved = runner._fingerprints.save.await_args.args[2]
        assert (saved["folder_path"], saved["ancestor_ids"]) == ("Specs", ["f-docs", "root"])

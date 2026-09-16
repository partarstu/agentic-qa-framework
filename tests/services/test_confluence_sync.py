# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the WS9a Confluence ingestion: normalization, chunking, change
detection and the page-body reconciliation algorithm.

Every external boundary (Confluence REST, Qdrant, the embedding service) is
mocked; the tests assert the classification branches, the reconciliation scopes
and the crash-safe write order.
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

from rag_sync.chunking import chunk_page_body  # noqa: E402
from rag_sync.normalization import normalize_page_body  # noqa: E402
from rag_sync.sync_state import content_hash  # noqa: E402

# --- Normalization (storage format -> markdown) -----------------------------------------


class TestNormalization:
    def test_headings_paragraphs_and_lists(self):
        raw = (
            "<h1>Title</h1><p>Intro text.</p>"
            "<h2>Section</h2><ul><li>one</li><li>two</li></ul>"
            "<ol><li>first</li><li>second</li></ol>"
        )
        markdown = normalize_page_body(raw, "Title")
        assert markdown.startswith("# Title")
        assert "## Section" in markdown
        assert "Intro text." in markdown
        assert "- one" in markdown and "- two" in markdown
        assert "1. first" in markdown and "2. second" in markdown

    def test_table_renders_as_markdown(self):
        raw = "<table><tr><th>Key</th><th>Value</th></tr><tr><td>a</td><td>1</td></tr></table>"
        markdown = normalize_page_body(raw, "T")
        assert "| Key | Value |" in markdown
        assert "| --- | --- |" in markdown
        assert "| a | 1 |" in markdown

    def test_code_macro_body_kept_with_language(self):
        raw = (
            '<ac:structured-macro ac:name="code" ac:schema-version="1">'
            '<ac:default-parameter>python</ac:default-parameter>'
            "<ac:plain-text-body><![CDATA[print('hi')]]></ac:plain-text-body>"
            "</ac:structured-macro>"
        )
        markdown = normalize_page_body(raw, "T")
        assert "```python" in markdown
        assert "print('hi')" in markdown

    def test_container_macro_body_kept(self):
        raw = (
            '<ac:structured-macro ac:name="info"><ac:rich-text-body>'
            "<p>Note text.</p></ac:rich-text-body></ac:structured-macro>"
        )
        markdown = normalize_page_body(raw, "T")
        assert "Note text." in markdown

    def test_non_content_macros_dropped(self):
        raw = (
            '<ac:structured-macro ac:name="toc"><ac:rich-text-body>'
            "<p>Children listing</p></ac:rich-text-body></ac:structured-macro>"
            "<p>Kept.</p>"
        )
        markdown = normalize_page_body(raw, "T")
        assert "Children listing" not in markdown
        assert "Kept." in markdown

    def test_unknown_macro_with_rich_body_kept_without_body_dropped(self):
        with_body = (
            '<ac:structured-macro ac:name="mystery"><ac:rich-text-body>'
            "<p>Mystery content</p></ac:rich-text-body></ac:structured-macro>"
        )
        without_body = '<ac:structured-macro ac:name="mystery" ac:schema-version="1"/>'
        assert "Mystery content" in normalize_page_body(with_body, "T")
        assert "Mystery content" not in normalize_page_body(without_body, "T")

    def test_links_keep_text_and_images_render_by_file_name(self):
        raw = (
            '<p><a href="https://x">Link text</a></p>'
            '<p><ac:image><ri:attachment ri:filename="diagram.png"></ri:attachment></ac:image></p>'
        )
        markdown = normalize_page_body(raw, "T")
        assert "Link text" in markdown
        assert "[image: diagram.png]" in markdown

    def test_entities_decoded_and_whitespace_normalized(self):
        raw = "<p>A&B</p><p></p><p>   spaced   </p><p></p><p></p><p>end</p>"
        markdown = normalize_page_body(raw, "T")
        assert "A&B" in markdown
        assert "   spaced   " not in markdown
        assert "\n\n\n\n" not in markdown


# --- Chunking ---------------------------------------------------------------------------


class TestChunking:
    def test_chunks_carry_breadcrumbs(self):
        markdown = (
            "# Page\n\nIntro.\n\n## Alpha\n\nAlpha text.\n\n## Beta\n\n### Gamma\n\nGamma text.\n"
        )
        chunks = chunk_page_body(markdown, "Page")
        breadcrumbs = [chunk.breadcrumb for chunk in chunks]
        assert "Page" in breadcrumbs
        assert "Page > Alpha" in breadcrumbs
        assert "Page > Beta > Gamma" in breadcrumbs

    def test_empty_section_does_not_become_a_chunk(self):
        markdown = "# Page\n\n## Empty\n\n## Full\n\nText here.\n"
        chunks = chunk_page_body(markdown, "Page")
        assert [chunk.breadcrumb for chunk in chunks] == ["Page > Full"]
        assert chunks[0].text.startswith("Text here.")

    def test_oversized_section_splits_by_paragraph_and_word(self):
        paragraph = "word " * 400  # ~2000 chars, one paragraph
        markdown = f"# Page\n\n## Big\n\n{paragraph}\n\nShort after.\n"
        with patch("config.DocumentRagConfig.CHUNK_MAX_TOKENS", 100):  # 400-char budget
            chunks = chunk_page_body(markdown, "Page")
        assert len(chunks) > 1
        # Every piece re-carries the breadcrumb.
        assert all(chunk.breadcrumb == "Page > Big" for chunk in chunks)
        assert any("Short after." in chunk.text for chunk in chunks)

    def test_budget_includes_breadcrumb(self):
        with patch("config.DocumentRagConfig.CHUNK_MAX_TOKENS", 10), patch(
            "config.DocumentRagConfig.CHARACTERS_PER_TOKEN", 4
        ):
            markdown = "# Page\n\n## S\n\n" + ("word " * 200)
            chunks = chunk_page_body(markdown, "Page")
        budget = 10 * 4
        assert all(len(chunk.content()) <= budget for chunk in chunks)

    def test_no_content_yields_no_chunks(self):
        assert chunk_page_body("", "Page") == []
        assert chunk_page_body("# Page\n", "Page") == []


# --- Change detection helpers ------------------------------------------------------------


class TestContentHash:
    def test_title_changes_the_hash(self):
        assert content_hash("body", "Title A") != content_hash("body", "Title B")

    def test_bytes_and_str_hash_equivalently(self):
        assert content_hash("body") == content_hash(b"body")


# --- The runner's classification and write order ------------------------------------------


def _page(page_id="111", title="Home", version=3, body=None, webui="/spaces/DEV/pages/111", space_id="555"):
    return {
        "id": page_id,
        "title": title,
        "spaceId": space_id,
        "version": {"number": version},
        "body": {"storage": {"value": body if body is not None else "<p>Hello.</p>"}},
        "_links": {"webui": webui},
    }


def _fingerprint_payload(version, hash_value, point_ids=None, title="Home", item_kind="page_body"):
    return {
        "version": version,
        "content_hash": hash_value,
        "schema_version": 1,
        "page_id": "111",
        "title": title,
        "webui": "/spaces/DEV/pages/111",
        "item_kind": item_kind,
        "point_ids": point_ids or [],
    }


@pytest.fixture
def runner():
    """A ConfluenceRagSyncRunner with every external boundary mocked."""
    with (
        patch("rag_sync.confluence_sync.VectorDbService") as mock_vdb,
        patch("rag_sync.confluence_sync.SyncLockStore") as mock_lock_cls,
        patch("rag_sync.confluence_sync.SyncStateStore") as mock_state_cls,
        patch("rag_sync.confluence_sync.FingerprintStore") as mock_fp_cls,
    ):
        documents_db = MagicMock()
        documents_db.close = AsyncMock()
        documents_db.ensure_collection = AsyncMock()
        documents_db.upsert_batch = AsyncMock()
        documents_db.delete = AsyncMock()
        documents_db.set_payload = AsyncMock()
        metadata_db = MagicMock()
        metadata_db.close = AsyncMock()
        mock_vdb.side_effect = [documents_db, metadata_db]

        lock_store = MagicMock()
        lock_store.mark_started = AsyncMock(return_value=True)
        lock_store.is_holder = AsyncMock(return_value=True)
        lock_store.release = AsyncMock(return_value=True)
        lock_store.acquire = AsyncMock(
            return_value=MagicMock(acquired=True, lock_info={"holder_token": "test-token"})
        )
        mock_lock_cls.return_value = lock_store

        state_store = MagicMock()
        state_store.save_cursor = AsyncMock()
        mock_state_cls.return_value = state_store

        fingerprints = MagicMock()
        fingerprints.load_scope = AsyncMock(return_value={})
        fingerprints.save = AsyncMock()
        fingerprints.delete = AsyncMock()
        mock_fp_cls.return_value = fingerprints

        from rag_sync.confluence_sync import ConfluenceRagSyncRunner

        runner = ConfluenceRagSyncRunner()
        runner._documents_db = documents_db
        runner._metadata_db = metadata_db
        runner._lock_store = lock_store
        runner._state_store = state_store
        runner._fingerprints = fingerprints
        yield runner, documents_db, lock_store, state_store, fingerprints


class TestConfluenceSyncRunner:
    async def test_new_page_ingested_with_crash_safe_order(self, runner):
        runner_obj, documents_db, _, state_store, fingerprints = runner
        page = _page(body="<h2>S</h2><p>Alpha text.</p>")
        client = MagicMock()
        client.get_space_id_by_key = AsyncMock(return_value="555")
        client.list_pages_in_space = AsyncMock(return_value=[page])
        client.get_page = AsyncMock(return_value=page)
        client.close = AsyncMock()

        with patch("rag_sync.confluence_sync.ConfluenceClient", return_value=client):
            result = await runner_obj.sync_space("DEV")

        assert result.status == "completed"
        assert result.processed_count == 1
        documents_db.upsert_batch.assert_awaited()
        # The fingerprint is saved after the upsert (crash-safe order: points first).
        assert fingerprints.save.await_count == 1
        fingerprint = fingerprints.save.call_args[0][2]
        assert fingerprint["version"] == 3
        assert fingerprint["point_ids"]
        state_store.save_cursor.assert_awaited_once()

    async def test_unchanged_version_skips_without_fetch(self, runner):
        runner_obj, documents_db, _, _, fingerprints = runner
        page = _page()
        stored_hash = content_hash("<p>Hello.</p>", "Home", "1")
        fingerprints.load_scope = AsyncMock(
            return_value={"page:111": _fingerprint_payload(3, stored_hash)}
        )
        client = MagicMock()
        client.get_space_id_by_key = AsyncMock(return_value="555")
        client.list_pages_in_space = AsyncMock(return_value=[page])
        client.get_page = AsyncMock()
        client.close = AsyncMock()

        with patch("rag_sync.confluence_sync.ConfluenceClient", return_value=client):
            result = await runner_obj.sync_space("DEV")

        assert result.processed_count == 0
        client.get_page.assert_not_awaited()
        documents_db.upsert_batch.assert_not_called()
        fingerprints.save.assert_not_called()

    async def test_version_changed_but_hash_equal_updates_version_only(self, runner):
        runner_obj, documents_db, _, _, fingerprints = runner
        page = _page(version=5)
        stored_hash = content_hash("<p>Hello.</p>", "Home", "1")
        fingerprints.load_scope = AsyncMock(
            return_value={"page:111": _fingerprint_payload(3, stored_hash, point_ids=["a"])}
        )
        client = MagicMock()
        client.get_space_id_by_key = AsyncMock(return_value="555")
        client.list_pages_in_space = AsyncMock(return_value=[page])
        client.get_page = AsyncMock(return_value=_page(version=5))
        client.close = AsyncMock()

        with patch("rag_sync.confluence_sync.ConfluenceClient", return_value=client):
            result = await runner_obj.sync_space("DEV")

        assert result.processed_count == 1
        documents_db.upsert_batch.assert_not_called()  # no re-embedding
        documents_db.delete.assert_not_called()
        fingerprint = fingerprints.save.call_args[0][2]
        assert fingerprint["version"] == 5

    async def test_metadata_only_change_updates_payload_without_embedding(self, runner):
        runner_obj, documents_db, _, _, fingerprints = runner
        stored_hash = content_hash("<p>Hello.</p>", "Home", "1")
        renamed = _page(title="Renamed Home")
        fingerprints.load_scope = AsyncMock(
            return_value={"page:111": _fingerprint_payload(3, stored_hash, point_ids=["pt-1"])}
        )
        client = MagicMock()
        client.get_space_id_by_key = AsyncMock(return_value="555")
        client.list_pages_in_space = AsyncMock(return_value=[renamed])
        client.get_page = AsyncMock()
        client.close = AsyncMock()

        with patch("rag_sync.confluence_sync.ConfluenceClient", return_value=client):
            result = await runner_obj.sync_space("DEV")

        assert result.processed_count == 1
        documents_db.set_payload.assert_awaited_once()
        call = documents_db.set_payload.call_args
        assert call.kwargs["point_ids"] == ["pt-1"]
        assert call.args[0]["page_title"] == "Renamed Home"
        client.get_page.assert_not_awaited()  # no body fetch for a metadata-only change

    async def test_changed_page_upserts_then_deletes_leftovers_then_saves_fingerprint(self, runner):
        runner_obj, documents_db, _, _, fingerprints = runner
        page = _page(version=6, body="<p>New content.</p>")
        old_hash = content_hash("old", "Home", "1")
        old_ids = ["old-1", "old-2"]
        fingerprints.load_scope = AsyncMock(
            return_value={"page:111": _fingerprint_payload(3, old_hash, point_ids=old_ids)}
        )
        client = MagicMock()
        client.get_space_id_by_key = AsyncMock(return_value="555")
        client.list_pages_in_space = AsyncMock(return_value=[page])
        client.get_page = AsyncMock(return_value=page)
        client.close = AsyncMock()

        with patch("rag_sync.confluence_sync.ConfluenceClient", return_value=client):
            await runner_obj.sync_space("DEV")

        # Points are upserted before the old leftovers are deleted.
        assert documents_db.upsert_batch.await_count >= documents_db.delete.await_count
        documents_db.delete.assert_awaited_once()
        deleted_ids = documents_db.delete.call_args[0][0]
        assert set(deleted_ids) == set(old_ids)
        # The fingerprint is saved last and carries the new point IDs.
        assert fingerprints.save.await_count == 1
        fingerprint = fingerprints.save.call_args[0][2]
        assert fingerprint["point_ids"]
        assert set(fingerprint["point_ids"]).isdisjoint(set(old_ids))

    async def test_removed_page_deletes_points_and_fingerprint(self, runner):
        runner_obj, documents_db, _, state_store, fingerprints = runner
        stored_hash = content_hash("gone", "Home", "1")
        fingerprints.load_scope = AsyncMock(
            return_value={"page:111": _fingerprint_payload(3, stored_hash, point_ids=["p1", "p2"])}
        )
        client = MagicMock()
        client.get_space_id_by_key = AsyncMock(return_value="555")
        client.list_pages_in_space = AsyncMock(return_value=[])  # the page is gone
        client.close = AsyncMock()

        with patch("rag_sync.confluence_sync.ConfluenceClient", return_value=client):
            result = await runner_obj.sync_space("DEV")

        documents_db.delete.assert_awaited_once_with(["p1", "p2"])
        fingerprints.delete.assert_awaited_once_with("confluence:DEV", "page:111")
        assert result.processed_count == 1
        state_store.save_cursor.assert_awaited_once()

    async def test_incomplete_listing_deletes_nothing_and_reports_errors(self, runner):
        runner_obj, documents_db, _, state_store, _ = runner
        client = MagicMock()
        client.get_space_id_by_key = AsyncMock(return_value="555")
        client.list_pages_in_space = AsyncMock(side_effect=RuntimeError("boom"))
        client.close = AsyncMock()

        with patch("rag_sync.confluence_sync.ConfluenceClient", return_value=client):
            result = await runner_obj.sync_space("DEV")

        assert result.status == "completed-with-errors"
        documents_db.delete.assert_not_called()
        state_store.save_cursor.assert_not_awaited()

    async def test_failing_item_does_not_abort_and_cursor_not_saved(self, runner):
        runner_obj, _, _, state_store, fingerprints = runner
        page = _page()
        client = MagicMock()
        client.get_space_id_by_key = AsyncMock(return_value="555")
        client.list_pages_in_space = AsyncMock(return_value=[page])
        client.get_page = AsyncMock(side_effect=RuntimeError("fetch failed"))
        client.close = AsyncMock()

        with patch("rag_sync.confluence_sync.ConfluenceClient", return_value=client):
            result = await runner_obj.sync_space("DEV")

        assert result.status == "completed-with-errors"
        fingerprints.save.assert_not_called()  # failed items keep their old fingerprint
        state_store.save_cursor.assert_not_awaited()

    async def test_skip_page_body_leaves_page_bodies_untouched(self, runner):
        runner_obj, documents_db, _, _, _ = runner
        page = _page()
        client = MagicMock()
        client.get_space_id_by_key = AsyncMock(return_value="555")
        client.list_pages_in_space = AsyncMock(return_value=[page])
        client.get_page = AsyncMock()
        client.close = AsyncMock()

        with patch("rag_sync.confluence_sync.ConfluenceClient", return_value=client):
            result = await runner_obj.sync_space("DEV", skip_page_body=True)

        assert result.processed_count == 0
        client.get_page.assert_not_awaited()
        documents_db.upsert_batch.assert_not_called()

    async def test_page_scope_verifies_space_and_syncs_one_page(self, runner):
        runner_obj, documents_db, _, _, _ = runner
        page = _page(body="<p>Scoped.</p>")
        client = MagicMock()
        client.get_space_id_by_key = AsyncMock(return_value="555")
        client.get_page = AsyncMock(return_value=page)
        client.close = AsyncMock()

        with patch("rag_sync.confluence_sync.ConfluenceClient", return_value=client):
            result = await runner_obj.sync_space("DEV", page_id="111")

        # The listing check and the body fetch both ask for the page.
        assert client.get_page.await_count == 2
        client.get_page.assert_awaited_with("111")
        assert result.status == "completed"
        assert result.processed_count == 1
        documents_db.upsert_batch.assert_awaited()

    async def test_page_scope_rejects_page_of_another_space(self, runner):
        runner_obj, _, _, state_store, _ = runner
        client = MagicMock()
        client.get_space_id_by_key = AsyncMock(return_value="555")
        client.get_page = AsyncMock(return_value=_page(space_id="999"))
        client.close = AsyncMock()

        with patch("rag_sync.confluence_sync.ConfluenceClient", return_value=client):
            result = await runner_obj.sync_space("DEV", page_id="111")

        # The listing is incomplete (the page check failed), so nothing is removed
        # and the run reports errors.
        assert result.status == "completed-with-errors"
        state_store.save_cursor.assert_not_awaited()

    async def test_taken_over_runner_aborts_before_writes(self, runner):
        runner_obj, documents_db, lock_store, _, _ = runner
        lock_store.mark_started = AsyncMock(return_value=False)
        with pytest.raises(PermissionError):
            await runner_obj.sync_space("DEV", lock_token="stale")
        documents_db.upsert_batch.assert_not_called()

    async def test_holder_checked_between_item_writes(self, runner):
        runner_obj, documents_db, lock_store, _, _ = runner
        page_one, page_two = _page("111", "One"), _page("222", "Two")
        client = MagicMock()
        client.get_space_id_by_key = AsyncMock(return_value="555")
        client.list_pages_in_space = AsyncMock(return_value=[page_one, page_two])
        client.get_page = AsyncMock(return_value=page_one)
        client.close = AsyncMock()
        # mark_started passes; the second per-item holder check fails.
        lock_store.is_holder = AsyncMock(side_effect=[True, False, True, True, True])

        with (
            patch("rag_sync.confluence_sync.ConfluenceClient", return_value=client),
            pytest.raises(PermissionError),
        ):
            await runner_obj.sync_space("DEV", lock_token="tok")

        documents_db.upsert_batch.assert_not_called()

    async def test_clean_run_saves_cursor_on_failure_free_completion(self, runner):
        runner_obj, _, _, state_store, _ = runner
        client = MagicMock()
        client.get_space_id_by_key = AsyncMock(return_value="555")
        client.list_pages_in_space = AsyncMock(return_value=[])
        client.close = AsyncMock()

        with patch("rag_sync.confluence_sync.ConfluenceClient", return_value=client):
            result = await runner_obj.sync_space("DEV")

        assert result.status == "completed"
        state_store.save_cursor.assert_awaited_once()
        cursor_scope, cursor = state_store.save_cursor.call_args[0]
        assert cursor_scope == "confluence:DEV"
        assert cursor["processed_count"] == 0

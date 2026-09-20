# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the document retrieval module (per-source retrieval)."""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import BinaryContent
from qdrant_client import models

from common.services.document_retrieval import (
    CONFLUENCE_SOURCE,
    SHAREPOINT_SOURCE,
    RetrievalScope,
    RetrievedPage,
    _scope_filter,
    assemble_retrieved_parts,
    retrieve_documents,
)


def _attachment_payload(**overrides) -> dict:
    payload = {
        "source": "confluence",
        "space_key": "DOC",
        "page_id": "111",
        "page_title": "Spec page",
        "page_url": "https://confluence/pages/111",
        "attachment_id": "att-1",
        "attachment_name": "spec.pdf",
        "media_type": "application/pdf",
        "content_kind": "attachment",
        "document_name": "spec.pdf",
        "breadcrumb": "Spec page > spec.pdf > page 1",
        "text": "breadcrumb plus content",
        "page_number": 1,
        "page_count": 2,
        "part_index": 1,
    }
    payload.update(overrides)
    return payload


def _body_payload(**overrides) -> dict:
    payload = {
        "source": "confluence",
        "space_key": "DOC",
        "page_id": "222",
        "page_title": "Design page",
        "page_url": "https://confluence/pages/222",
        "attachment_id": None,
        "attachment_name": None,
        "media_type": None,
        "content_kind": "page_body",
        "document_name": "Design page",
        "breadcrumb": "Design page",
        "text": "design body text",
        "page_number": None,
        "page_count": None,
        "part_index": 0,
    }
    payload.update(overrides)
    return payload


def _hit(payload: dict, score: float = 0.9) -> MagicMock:
    hit = MagicMock()
    hit.payload = payload
    hit.score = score
    return hit


@pytest.fixture
def documents_db() -> MagicMock:
    db = MagicMock()
    db.collection_name = "documents"
    db.client = MagicMock()
    db.scroll_points = AsyncMock(return_value=[])
    db.hybrid_search = AsyncMock(return_value=[])
    db.retrieve = AsyncMock(return_value=[])
    return db


@pytest.fixture
def sharepoint_db() -> MagicMock:
    db = MagicMock()
    db.collection_name = "sharepoint_documents"
    db.client = MagicMock()
    db.scroll_points = AsyncMock(return_value=[])
    db.hybrid_search = AsyncMock(return_value=[])
    db.retrieve = AsyncMock(return_value=[])
    return db


@pytest.fixture
def confluence_only(documents_db):
    """Confluence retrieval on, SharePoint off: the pre- single-source setup."""
    with (
        patch.object(config_documentrag(), "CONFLUENCE_RETRIEVAL_ENABLED", True),
        patch.object(config_documentrag(), "SHAREPOINT_RETRIEVAL_ENABLED", False),
    ):
        yield documents_db


def config_documentrag():
    from config import DocumentRagConfig

    return DocumentRagConfig


@pytest.mark.asyncio
async def test_no_hits_yield_no_pages(confluence_only):
    result = await retrieve_documents(confluence_only, "query")
    assert result.pages == []
    assert result.unavailable_sources == []
    confluence_only.hybrid_search.assert_awaited_once()


@pytest.mark.asyncio
async def test_scope_becomes_exact_payload_filter_pinned_to_the_source(confluence_only):
    await retrieve_documents(confluence_only, "query", RetrievalScope(space_key="DOC", page_id="111"))
    _, kwargs = confluence_only.hybrid_search.await_args
    query_filter = kwargs["query_filter"]
    keys = [condition.key for condition in query_filter.must]
    # The source discriminator is pinned on every query, even though the collection implies it.
    assert keys == ["source", "space_key", "page_id"]
    assert query_filter.must[0].match.value == CONFLUENCE_SOURCE


@pytest.mark.asyncio
async def test_every_query_pins_the_source_discriminator(confluence_only):
    await retrieve_documents(confluence_only, "query")
    _, kwargs = confluence_only.hybrid_search.await_args
    (source_condition,) = kwargs["query_filter"].must
    assert source_condition.key == "source"
    assert source_condition.match.value == CONFLUENCE_SOURCE


@pytest.mark.asyncio
async def test_name_pattern_with_no_match_returns_early(confluence_only):
    confluence_only.scroll_points = AsyncMock(return_value=[MagicMock(payload={"document_name": "spec.pdf"})])

    result = await retrieve_documents(confluence_only, "query", RetrievalScope(document_name_pattern="nomatch"))

    assert result.pages == []
    confluence_only.hybrid_search.assert_not_awaited()


@pytest.mark.asyncio
async def test_name_pattern_scrolls_then_filters_by_matched_names(confluence_only):
    confluence_only.scroll_points = AsyncMock(
        return_value=[
            MagicMock(payload={"document_name": "spec.pdf"}),
            MagicMock(payload={"document_name": "other.pdf"}),
        ]
    )
    confluence_only.hybrid_search = AsyncMock(return_value=[_hit(_attachment_payload())])

    result = await retrieve_documents(confluence_only, "query", RetrievalScope(document_name_pattern="spec"))

    _, kwargs = confluence_only.hybrid_search.await_args
    name_conditions = [c for c in kwargs["query_filter"].must if c.key == "document_name"]
    assert len(name_conditions) == 1
    assert name_conditions[0].match.any == ["spec.pdf"]
    assert len(result.pages) == 1


@pytest.mark.asyncio
async def test_hits_group_per_page_and_best_rank_wins(confluence_only):
    hits = [
        _hit(_attachment_payload(part_index=2, text="page 1 part 2"), score=0.9),
        _hit(_attachment_payload(part_index=3, text="page 1 part 3"), score=0.8),
        _hit(_attachment_payload(page_number=2, part_index=2, text="page 2"), score=0.7),
        _hit(_body_payload(), score=0.6),
    ]
    confluence_only.hybrid_search = AsyncMock(return_value=hits)
    confluence_only.retrieve = AsyncMock(return_value=[])

    result = await retrieve_documents(confluence_only, "query")

    assert [page.part.text for page in result.pages] == ["page 1 part 2", "page 2", "design body text"]
    # The page images are fetched by their deterministic part-0 vector IDs, in one batched call
    # covering both attachment pages (the page-body hit has no image).
    confluence_only.retrieve.assert_awaited_once()
    assert len(confluence_only.retrieve.await_args.args[0]) == 2


@pytest.mark.asyncio
async def test_page_image_is_decoded_from_part_zero(confluence_only):
    from common.models import DocumentPagePart

    image_b64 = base64.b64encode(b"png-bytes").decode()
    confluence_only.hybrid_search = AsyncMock(return_value=[_hit(_attachment_payload())])
    part0_id = DocumentPagePart.model_validate({**_attachment_payload(), "part_index": 0}).get_vector_id()
    part0_record = MagicMock()
    part0_record.id = part0_id
    part0_record.payload = {"image": image_b64}
    confluence_only.retrieve = AsyncMock(return_value=[part0_record])

    result = await retrieve_documents(confluence_only, "query")

    assert confluence_only.retrieve.await_args.args[0] == [part0_id]
    assert result.pages[0].image == b"png-bytes"


@pytest.mark.asyncio
async def test_a_failing_page_image_fetch_leaves_the_page_on_its_text(confluence_only):
    """A broken image read must not fail the whole grounded review (module isolation contract)."""
    confluence_only.hybrid_search = AsyncMock(return_value=[_hit(_attachment_payload())])
    confluence_only.retrieve = AsyncMock(side_effect=RuntimeError("qdrant down"))

    result = await retrieve_documents(confluence_only, "query")

    assert len(result.pages) == 1
    assert result.pages[0].image is None


def test_assemble_parts_prefers_image_over_text():
    parts = assemble_retrieved_parts([_page(image=b"png", text="fallback text")])
    assert isinstance(parts[0], str) and parts[0].startswith("Reference documentation:")
    assert isinstance(parts[1], BinaryContent)
    assert parts[1].identifier == "spec.pdf page 1"


def test_assemble_parts_falls_back_to_text():
    parts = assemble_retrieved_parts([_page(image=None)])
    assert parts[1] == "breadcrumb plus content"


def _page(image: bytes | None = None, **overrides) -> RetrievedPage:
    from common.models import DocumentPagePart

    part = DocumentPagePart.model_validate(_attachment_payload(**overrides))
    return RetrievedPage(part, image)


class TestPerSourceRetrieval:
    @pytest.mark.asyncio
    async def test_sharepoint_scope_fields_reach_only_the_sharepoint_query(self, documents_db, sharepoint_db):
        with (
            patch.object(config_documentrag(), "CONFLUENCE_RETRIEVAL_ENABLED", True),
            patch.object(config_documentrag(), "SHAREPOINT_RETRIEVAL_ENABLED", True),
        ):
            sharepoint_db.hybrid_search = AsyncMock(
                return_value=[_hit(_attachment_payload(source="sharepoint", space_key="", page_id=""))]
            )
            result = await retrieve_documents(
                documents_db, "query", RetrievalScope(drive_id="drive1"), sharepoint_db=sharepoint_db
            )

        confluence_filter = documents_db.hybrid_search.await_args.kwargs["query_filter"]
        assert [c.key for c in confluence_filter.must] == ["source"]
        sharepoint_filter = sharepoint_db.hybrid_search.await_args.kwargs["query_filter"]
        keys = [c.key for c in sharepoint_filter.must]
        assert keys == ["source", "drive_id"]
        assert sharepoint_filter.must[0].match.value == SHAREPOINT_SOURCE
        assert len(result.pages) == 1

    @pytest.mark.asyncio
    async def test_sources_are_merged_by_rank_interleaving(self, documents_db, sharepoint_db):
        with (
            patch.object(config_documentrag(), "CONFLUENCE_RETRIEVAL_ENABLED", True),
            patch.object(config_documentrag(), "SHAREPOINT_RETRIEVAL_ENABLED", True),
        ):
            documents_db.hybrid_search = AsyncMock(
                return_value=[_hit(_body_payload(text="c1"), 0.9), _hit(_body_payload(page_id="223", text="c2"), 0.8)]
            )
            sharepoint_db.hybrid_search = AsyncMock(
                return_value=[_hit(_body_payload(source="sharepoint", space_key="", page_id="", text="s1"), 0.95)]
            )

            result = await retrieve_documents(documents_db, "query", sharepoint_db=sharepoint_db)

        # Rank interleaving, not fused score: s1 outranks c1 despite the higher similarity, because
        # scores are not comparable across collections; each source's first page comes first.
        assert [page.part.text for page in result.pages] == ["c1", "s1", "c2"]

    @pytest.mark.asyncio
    async def test_a_failing_source_is_skipped_and_reported_unavailable(self, documents_db, sharepoint_db):
        with (
            patch.object(config_documentrag(), "CONFLUENCE_RETRIEVAL_ENABLED", True),
            patch.object(config_documentrag(), "SHAREPOINT_RETRIEVAL_ENABLED", True),
        ):
            documents_db.hybrid_search = AsyncMock(return_value=[_hit(_body_payload(text="c1"), 0.9)])
            sharepoint_db.hybrid_search = AsyncMock(side_effect=RuntimeError("collection gone"))

            result = await retrieve_documents(documents_db, "query", sharepoint_db=sharepoint_db)

        assert [page.part.text for page in result.pages] == ["c1"]
        assert result.unavailable_sources == ["sharepoint"]

    @pytest.mark.asyncio
    async def test_all_sources_failing_raises(self, documents_db, sharepoint_db):
        with (
            patch.object(config_documentrag(), "CONFLUENCE_RETRIEVAL_ENABLED", True),
            patch.object(config_documentrag(), "SHAREPOINT_RETRIEVAL_ENABLED", True),
        ):
            documents_db.hybrid_search = AsyncMock(side_effect=RuntimeError("down"))
            sharepoint_db.hybrid_search = AsyncMock(side_effect=RuntimeError("down"))

            with pytest.raises(RuntimeError, match="All document sources failed"):
                await retrieve_documents(documents_db, "query", sharepoint_db=sharepoint_db)

    @pytest.mark.asyncio
    async def test_no_enabled_source_yields_an_empty_result(self, documents_db):
        with (
            patch.object(config_documentrag(), "CONFLUENCE_RETRIEVAL_ENABLED", False),
            patch.object(config_documentrag(), "SHAREPOINT_RETRIEVAL_ENABLED", False),
        ):
            result = await retrieve_documents(documents_db, "query")

        assert result.pages == []
        documents_db.hybrid_search.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_enabled_source_without_a_collection_service_fails_that_source(self, sharepoint_db):
        with (
            patch.object(config_documentrag(), "CONFLUENCE_RETRIEVAL_ENABLED", False),
            patch.object(config_documentrag(), "SHAREPOINT_RETRIEVAL_ENABLED", True),
            pytest.raises(RuntimeError, match="All document sources failed"),
        ):
            await retrieve_documents(MagicMock(), "query", sharepoint_db=None)


class TestScopeFilterIsolation:
    def test_confluence_scope_ignores_sharepoint_fields(self):
        scope = RetrievalScope(space_key="DOC", drive_id="drive1", folder_path="Docs")
        confluence_filter = _scope_filter(scope, CONFLUENCE_SOURCE)
        assert [c.key for c in confluence_filter.must] == ["source", "space_key"]

    def test_sharepoint_scope_ignores_confluence_fields(self):
        scope = RetrievalScope(space_key="DOC", drive_id="drive1")
        sharepoint_filter = _scope_filter(scope, SHAREPOINT_SOURCE)
        assert [c.key for c in sharepoint_filter.must] == ["source", "drive_id"]

    def test_the_discriminator_is_pinned_even_without_a_scope(self):
        for source in (CONFLUENCE_SOURCE, SHAREPOINT_SOURCE):
            (condition,) = _scope_filter(None, source).must
            assert condition.key == "source" and condition.match.value == source

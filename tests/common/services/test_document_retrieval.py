# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the document retrieval module (per-source retrieval)."""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import BinaryContent
from qdrant_client import models

import config
from common.services.document_retrieval import (
    _HIT_PAYLOAD_INCLUDE,
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
    db.dense_search = AsyncMock(return_value=[])
    db.retrieve = AsyncMock(return_value=[])
    return db


@pytest.fixture
def sharepoint_db() -> MagicMock:
    db = MagicMock()
    db.collection_name = "sharepoint_documents"
    db.client = MagicMock()
    db.scroll_points = AsyncMock(return_value=[])
    db.dense_search = AsyncMock(return_value=[])
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
    pages = await retrieve_documents(confluence_only, ["query"])
    assert pages == []
    confluence_only.dense_search.assert_awaited_once()


@pytest.mark.asyncio
async def test_every_query_text_is_searched_in_one_call_with_the_relevance_gate(confluence_only):
    await retrieve_documents(confluence_only, ["refund limit", "PAY-REF-4"])

    args, kwargs = confluence_only.dense_search.await_args
    assert args[0] == ["refund limit", "PAY-REF-4"]
    assert kwargs["score_threshold"] == config.QdrantConfig.MIN_SIMILARITY_SCORE
    confluence_only.dense_search.assert_awaited_once()


@pytest.mark.asyncio
async def test_scope_becomes_exact_payload_filter_pinned_to_the_source(confluence_only):
    await retrieve_documents(confluence_only, ["query"], RetrievalScope(space_key="DOC", page_id="111"))
    _, kwargs = confluence_only.dense_search.await_args
    query_filter = kwargs["query_filter"]
    keys = [condition.key for condition in query_filter.must]
    # The source discriminator is pinned on every query, even though the collection implies it.
    assert keys == ["source", "space_key", "page_id"]
    assert query_filter.must[0].match.value == CONFLUENCE_SOURCE


@pytest.mark.asyncio
async def test_every_query_pins_the_source_discriminator(confluence_only):
    await retrieve_documents(confluence_only, ["query"])
    _, kwargs = confluence_only.dense_search.await_args
    (source_condition,) = kwargs["query_filter"].must
    assert source_condition.key == "source"
    assert source_condition.match.value == CONFLUENCE_SOURCE


@pytest.mark.asyncio
async def test_name_pattern_with_no_match_returns_early(confluence_only):
    confluence_only.scroll_points = AsyncMock(return_value=[MagicMock(payload={"document_name": "spec.pdf"})])

    pages = await retrieve_documents(confluence_only, ["query"], RetrievalScope(document_name_pattern="nomatch"))

    assert pages == []
    confluence_only.dense_search.assert_not_awaited()


@pytest.mark.asyncio
async def test_name_pattern_scrolls_then_filters_by_matched_names(confluence_only):
    confluence_only.scroll_points = AsyncMock(
        return_value=[
            MagicMock(payload={"document_name": "spec.pdf"}),
            MagicMock(payload={"document_name": "other.pdf"}),
        ]
    )
    confluence_only.dense_search = AsyncMock(return_value=[_hit(_attachment_payload())])

    pages = await retrieve_documents(confluence_only, ["query"], RetrievalScope(document_name_pattern="spec"))

    _, kwargs = confluence_only.dense_search.await_args
    name_conditions = [c for c in kwargs["query_filter"].must if c.key == "document_name"]
    assert len(name_conditions) == 1
    assert name_conditions[0].match.any == ["spec.pdf"]
    assert len(pages) == 1


@pytest.mark.asyncio
async def test_hits_group_per_page_and_best_rank_wins(confluence_only):
    hits = [
        _hit(_attachment_payload(part_index=2, text="page 1 part 2"), score=0.9),
        _hit(_attachment_payload(part_index=3, text="page 1 part 3"), score=0.8),
        _hit(_attachment_payload(page_number=2, part_index=2, text="page 2"), score=0.7),
        _hit(_body_payload(), score=0.6),
    ]
    confluence_only.dense_search = AsyncMock(return_value=hits)
    confluence_only.retrieve = AsyncMock(return_value=[])

    pages = await retrieve_documents(confluence_only, ["query"])

    assert [page.part.text for page in pages] == ["page 1 part 2", "page 2", "design body text"]
    # The page images are fetched by their deterministic part-0 vector IDs, in one batched call
    # covering both attachment pages (the page-body hit has no image).
    confluence_only.retrieve.assert_awaited_once()
    assert len(confluence_only.retrieve.await_args.args[0]) == 2


@pytest.mark.asyncio
async def test_page_image_is_decoded_from_part_zero(confluence_only):
    from common.models import DocumentPagePart

    image_b64 = base64.b64encode(b"png-bytes").decode()
    confluence_only.dense_search = AsyncMock(return_value=[_hit(_attachment_payload())])
    part0_id = DocumentPagePart.model_validate({**_attachment_payload(), "part_index": 0}).get_vector_id()
    part0_record = MagicMock()
    part0_record.id = part0_id
    part0_record.payload = {"image": image_b64}
    confluence_only.retrieve = AsyncMock(return_value=[part0_record])

    pages = await retrieve_documents(confluence_only, ["query"])

    assert confluence_only.retrieve.await_args.args[0] == [part0_id]
    assert pages[0].image == b"png-bytes"


@pytest.mark.asyncio
async def test_a_failing_page_image_fetch_leaves_the_page_on_its_text(confluence_only):
    """A broken image read must not fail the whole grounded review (module isolation contract)."""
    confluence_only.dense_search = AsyncMock(return_value=[_hit(_attachment_payload())])
    confluence_only.retrieve = AsyncMock(side_effect=RuntimeError("qdrant down"))

    pages = await retrieve_documents(confluence_only, ["query"])

    assert len(pages) == 1
    assert pages[0].image is None


def test_assemble_parts_prefers_image_over_text():
    parts = assemble_retrieved_parts([_page(image=b"png", text="fallback text")])
    assert isinstance(parts[0], str) and parts[0].startswith("Reference documentation:")
    assert isinstance(parts[1], BinaryContent)
    assert parts[1].identifier == "spec.pdf page 1"


@pytest.mark.asyncio
async def test_a_document_keeps_at_most_the_page_cap_and_counts_once_toward_the_document_bound(confluence_only):
    pages_of_big_document = [
        _hit(_attachment_payload(page_number=number, text=f"big {number}"), 0.9 - number / 100)
        for number in range(1, 9)
    ]
    other_documents = [
        _hit(_attachment_payload(attachment_id=f"att-{n}", document_name=f"doc{n}.pdf", text=f"doc{n}"), 0.5)
        for n in range(2, 8)
    ]
    confluence_only.dense_search = AsyncMock(return_value=[*pages_of_big_document, *other_documents])

    with patch.object(config.QdrantConfig, "MAX_RETRIEVED_PAGES_PER_DOCUMENT", 3):
        pages = await retrieve_documents(confluence_only, ["query"])

    assert [page.part.text for page in pages] == ["big 1", "big 2", "big 3", "doc2", "doc3", "doc4", "doc5"]
    assert {page.part.attachment_id for page in pages} == {"att-1", "att-2", "att-3", "att-4", "att-5"}


@pytest.mark.asyncio
async def test_the_search_fetches_enough_points_for_every_document_to_fill_its_page_cap(confluence_only):
    with patch.object(config.QdrantConfig, "MAX_RETRIEVED_PAGES_PER_DOCUMENT", 4):
        await retrieve_documents(confluence_only, ["query"], limit=3)

    assert confluence_only.dense_search.await_args.kwargs["limit"] == 12


@pytest.mark.asyncio
async def test_the_document_bound_spans_the_sources(documents_db, sharepoint_db):
    with (
        patch.object(config_documentrag(), "CONFLUENCE_RETRIEVAL_ENABLED", True),
        patch.object(config_documentrag(), "SHAREPOINT_RETRIEVAL_ENABLED", True),
    ):
        documents_db.dense_search = AsyncMock(
            return_value=[_hit(_body_payload(page_id=str(n), text=f"c{n}")) for n in range(3)]
        )
        sharepoint_db.dense_search = AsyncMock(
            return_value=[_hit(_body_payload(source="sharepoint", page_id=str(n), text=f"s{n}")) for n in range(3)]
        )

        pages = await retrieve_documents(documents_db, ["query"], sharepoint_db=sharepoint_db, limit=4)

    assert [page.part.text for page in pages] == ["c0", "s0", "c1", "s1"]


def test_an_attachment_page_header_identifies_the_file_page_and_location():
    parts = assemble_retrieved_parts(
        [
            _page(
                source="sharepoint",
                attachment_name="FEH_Payments_Spec_v2.pdf",
                page_number=4,
                page_count=6,
                folder_path="Specs",
                page_url="https://ignored",
            )
        ]
    )
    assert (
        parts[0] == "Reference documentation: FEH_Payments_Spec_v2.pdf, page 4 of 6 (source: sharepoint; folder: Specs)"
    )


def test_a_confluence_attachment_header_names_the_space_and_the_host_page():
    parts = assemble_retrieved_parts([_page()])
    assert (
        parts[0]
        == "Reference documentation: spec.pdf, page 1 of 2 (source: confluence; space: DOC; Confluence page: Spec page)"
    )


def test_a_page_body_header_identifies_the_title_and_one_based_chunk_number():
    from common.models import DocumentPagePart

    part = DocumentPagePart.model_validate(_body_payload(part_index=2))
    parts = assemble_retrieved_parts([RetrievedPage(part, None)])
    assert parts[0] == (
        "Reference documentation: Design page, chunk 3 "
        "(source: confluence; space: DOC; URL: https://confluence/pages/222)"
    )


def test_assemble_parts_falls_back_to_text():
    parts = assemble_retrieved_parts([_page(image=None)])
    assert parts[1] == "breadcrumb plus content"


def test_assemble_parts_omits_a_page_with_neither_image_nor_text():
    assert assemble_retrieved_parts([_page(image=None, text="")]) == []


def test_the_hit_payload_selector_carries_every_field_a_page_part_requires():
    """Without this the hits validate in the tests and fail in production, where the selector applies."""
    from common.models import DocumentPagePart

    required = {name for name, field in DocumentPagePart.model_fields.items() if field.is_required()}
    assert required <= set(_HIT_PAYLOAD_INCLUDE)


def test_the_hit_payload_selector_carries_the_metadata_the_header_shows():
    assert {"folder_path", "space_key", "page_title", "page_url", "page_count"} <= set(_HIT_PAYLOAD_INCLUDE)


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
            sharepoint_db.dense_search = AsyncMock(
                return_value=[_hit(_attachment_payload(source="sharepoint", space_key="", page_id=""))]
            )
            pages = await retrieve_documents(
                documents_db, ["query"], RetrievalScope(drive_id="drive1"), sharepoint_db=sharepoint_db
            )

        confluence_filter = documents_db.dense_search.await_args.kwargs["query_filter"]
        assert [c.key for c in confluence_filter.must] == ["source"]
        sharepoint_filter = sharepoint_db.dense_search.await_args.kwargs["query_filter"]
        keys = [c.key for c in sharepoint_filter.must]
        assert keys == ["source", "drive_id"]
        assert sharepoint_filter.must[0].match.value == SHAREPOINT_SOURCE
        assert len(pages) == 1

    @pytest.mark.asyncio
    async def test_sources_are_merged_by_rank_interleaving(self, documents_db, sharepoint_db):
        with (
            patch.object(config_documentrag(), "CONFLUENCE_RETRIEVAL_ENABLED", True),
            patch.object(config_documentrag(), "SHAREPOINT_RETRIEVAL_ENABLED", True),
        ):
            documents_db.dense_search = AsyncMock(
                return_value=[_hit(_body_payload(text="c1"), 0.9), _hit(_body_payload(page_id="223", text="c2"), 0.8)]
            )
            sharepoint_db.dense_search = AsyncMock(
                return_value=[_hit(_body_payload(source="sharepoint", space_key="", page_id="", text="s1"), 0.95)]
            )

            pages = await retrieve_documents(documents_db, ["query"], sharepoint_db=sharepoint_db)

        # Rank interleaving, not fused score: s1 outranks c1 despite the higher similarity, because
        # scores are not comparable across collections; each source's first page comes first.
        assert [page.part.text for page in pages] == ["c1", "s1", "c2"]

    @pytest.mark.asyncio
    async def test_one_failing_source_fails_the_retrieval(self, documents_db, sharepoint_db):
        with (
            patch.object(config_documentrag(), "CONFLUENCE_RETRIEVAL_ENABLED", True),
            patch.object(config_documentrag(), "SHAREPOINT_RETRIEVAL_ENABLED", True),
        ):
            documents_db.dense_search = AsyncMock(return_value=[_hit(_body_payload(text="c1"), 0.9)])
            sharepoint_db.dense_search = AsyncMock(side_effect=RuntimeError("collection gone"))

            with pytest.raises(RuntimeError, match="Document retrieval failed for: sharepoint"):
                await retrieve_documents(documents_db, ["query"], sharepoint_db=sharepoint_db)

    @pytest.mark.asyncio
    async def test_all_sources_failing_raises(self, documents_db, sharepoint_db):
        with (
            patch.object(config_documentrag(), "CONFLUENCE_RETRIEVAL_ENABLED", True),
            patch.object(config_documentrag(), "SHAREPOINT_RETRIEVAL_ENABLED", True),
        ):
            documents_db.dense_search = AsyncMock(side_effect=RuntimeError("down"))
            sharepoint_db.dense_search = AsyncMock(side_effect=RuntimeError("down"))

            with pytest.raises(RuntimeError, match="Document retrieval failed for: confluence, sharepoint"):
                await retrieve_documents(documents_db, ["query"], sharepoint_db=sharepoint_db)

    @pytest.mark.asyncio
    async def test_no_enabled_source_yields_an_empty_result(self, documents_db):
        with (
            patch.object(config_documentrag(), "CONFLUENCE_RETRIEVAL_ENABLED", False),
            patch.object(config_documentrag(), "SHAREPOINT_RETRIEVAL_ENABLED", False),
        ):
            pages = await retrieve_documents(documents_db, ["query"])

        assert pages == []
        documents_db.dense_search.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_enabled_source_without_a_collection_service_fails_that_source(self, sharepoint_db):
        with (
            patch.object(config_documentrag(), "CONFLUENCE_RETRIEVAL_ENABLED", False),
            patch.object(config_documentrag(), "SHAREPOINT_RETRIEVAL_ENABLED", True),
            pytest.raises(RuntimeError, match="Document retrieval failed for: sharepoint"),
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

    def test_a_sharepoint_folder_scope_matches_the_folder_and_its_subfolders(self):
        scope = RetrievalScope(drive_id="drive1", folder_path="/Specs/")

        folder_condition = _scope_filter(scope, SHAREPOINT_SOURCE).must[-1]

        # Every stored part lists each prefix of its folder path, so "Specs" matches "Specs/Archive" too.
        assert (folder_condition.key, folder_condition.match.value) == ("folder_ancestors", "Specs")

    def test_the_discriminator_is_pinned_even_without_a_scope(self):
        for source in (CONFLUENCE_SOURCE, SHAREPOINT_SOURCE):
            (condition,) = _scope_filter(None, source).must
            assert condition.key == "source" and condition.match.value == source

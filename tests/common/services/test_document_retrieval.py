# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the document retrieval module (WS10)."""

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.messages import BinaryContent
from qdrant_client import models

from common.services.document_retrieval import (
    RetrievalScope,
    RetrievedPage,
    assemble_retrieved_parts,
    retrieve_documents,
)


def _attachment_payload(**overrides) -> dict:
    payload = {
        "space_key": "DOC",
        "page_id": "111",
        "page_title": "Spec page",
        "page_url": "https://confluence/pages/111",
        "attachment_id": "att-1",
        "attachment_name": "spec.pdf",
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
        "space_key": "DOC",
        "page_id": "222",
        "page_title": "Design page",
        "page_url": "https://confluence/pages/222",
        "attachment_id": None,
        "attachment_name": None,
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
    db.client.scroll = AsyncMock(return_value=([], None))
    db.hybrid_search = AsyncMock(return_value=[])
    db.retrieve = AsyncMock(return_value=[])
    return db


@pytest.mark.asyncio
async def test_no_hits_yield_no_pages(documents_db):
    assert await retrieve_documents(documents_db, "query") == []
    documents_db.hybrid_search.assert_awaited_once()


@pytest.mark.asyncio
async def test_scope_becomes_exact_payload_filter(documents_db):
    await retrieve_documents(documents_db, "query", RetrievalScope(space_key="DOC", page_id="111"))
    _, kwargs = documents_db.hybrid_search.await_args
    query_filter = kwargs["query_filter"]
    keys = [condition.key for condition in query_filter.must]
    assert keys == ["space_key", "page_id"]


@pytest.mark.asyncio
async def test_name_pattern_with_no_match_returns_early(documents_db):
    documents_db.client.scroll = AsyncMock(return_value=([MagicMock(payload={"document_name": "spec.pdf"})], None))

    pages = await retrieve_documents(documents_db, "query", RetrievalScope(document_name_pattern="nomatch"))

    assert pages == []
    documents_db.hybrid_search.assert_not_awaited()


@pytest.mark.asyncio
async def test_name_pattern_scrolls_then_filters_by_matched_names(documents_db):
    async def scroll(**kwargs):
        if kwargs.get("offset") is None:
            return [MagicMock(payload={"document_name": "spec.pdf"})], MagicMock()
        return [MagicMock(payload={"document_name": "other.pdf"})], None

    documents_db.client.scroll = AsyncMock(side_effect=scroll)
    documents_db.hybrid_search = AsyncMock(return_value=[_hit(_attachment_payload())])

    pages = await retrieve_documents(documents_db, "query", RetrievalScope(document_name_pattern="spec"))

    _, kwargs = documents_db.hybrid_search.await_args
    name_conditions = [c for c in kwargs["query_filter"].must if c.key == "document_name"]
    assert len(name_conditions) == 1
    assert name_conditions[0].match.any == ["spec.pdf"]
    assert len(pages) == 1


@pytest.mark.asyncio
async def test_hits_group_per_page_and_best_rank_wins(documents_db):
    hits = [
        _hit(_attachment_payload(part_index=2, text="page 1 part 2"), score=0.9),
        _hit(_attachment_payload(part_index=3, text="page 1 part 3"), score=0.8),
        _hit(_attachment_payload(page_number=2, part_index=2, text="page 2"), score=0.7),
        _hit(_body_payload(), score=0.6),
    ]
    documents_db.hybrid_search = AsyncMock(return_value=hits)
    documents_db.retrieve = AsyncMock(return_value=[])

    pages = await retrieve_documents(documents_db, "query")

    assert [page.part.text for page in pages] == ["page 1 part 2", "page 2", "design body text"]
    # The page image of each attachment page is fetched via its deterministic part-0 vector ID.
    assert documents_db.retrieve.await_count == 2
    for call in documents_db.retrieve.await_args_list:
        assert len(call.args[0]) == 1


@pytest.mark.asyncio
async def test_page_image_is_decoded_from_part_zero(documents_db):
    image_b64 = base64.b64encode(b"png-bytes").decode()
    documents_db.hybrid_search = AsyncMock(return_value=[_hit(_attachment_payload())])
    part0_record = MagicMock()
    part0_record.payload = {"image": image_b64}
    documents_db.retrieve = AsyncMock(return_value=[part0_record])

    pages = await retrieve_documents(documents_db, "query")

    assert pages[0].image == b"png-bytes"


def _page(image: bytes | None = None, **overrides) -> RetrievedPage:
    from common.models import DocumentPagePart

    part = DocumentPagePart.model_validate(_attachment_payload(**overrides))
    return RetrievedPage(part, image)


def test_assemble_parts_prefers_image_over_text():
    parts = assemble_retrieved_parts([_page(image=b"png", text="fallback text")])
    assert isinstance(parts[0], str) and parts[0].startswith("Reference documentation:")
    assert isinstance(parts[1], BinaryContent)
    assert parts[1].identifier == "spec.pdf page 1"


def test_assemble_parts_falls_back_to_text():
    parts = assemble_retrieved_parts([_page(image=None)])
    assert parts[1] == "breadcrumb plus content"


def test_assemble_parts_omits_page_without_content():
    from common.models import DocumentPagePart

    body = DocumentPagePart.model_validate(_body_payload(text=""))
    parts = assemble_retrieved_parts([RetrievedPage(body, None)])
    assert parts == ["Reference documentation: Design page (https://confluence/pages/222)"]


def test_scope_filter_handles_missing_scope():
    from common.services.document_retrieval import _scope_filter

    assert _scope_filter(None) is None
    assert _scope_filter(RetrievalScope()) is None
    assert isinstance(_scope_filter(RetrievalScope(space_key="DOC")), models.Filter)

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Scoped hybrid retrieval over the documents collection (WS10).

One retrieval turns a query text plus an optional scope (space key, page ID,
document-name pattern) into assembled, review-ready documentation parts:

1. Scope filters (space, page) become exact payload filters.
2. Qdrant has no regex filter, so a document-name pattern is resolved first: the
   distinct document names under the remaining filters are scrolled, matched
   client-side and queried with an exact MatchAny filter. No match means an empty
   result without running the query at all.
3. The shared hybrid query runs with the page image excluded from the payload.
4. Hits are grouped per page (an attachment page is one attachment ID + page
   number; a page-body chunk stands alone) and the best rank per page wins.
5. The page image of each surviving page is fetched by reconstructing its
   deterministic part-0 point ID.
6. Every page contributes a header text part plus exactly one content part: the
   page image when present, otherwise its text; a page with neither is omitted.

Runtime failures (embedding service, Qdrant) propagate to the caller; the
Requirements Review tool turns them into a failed review.
"""

from pydantic_ai.messages import BinaryContent
from qdrant_client import models

import config
from common import utils
from common.models import DocumentPagePart
from common.services.vector_db_service import VectorDbService

logger = utils.get_logger("document_retrieval")

# Payload fields fetched per hit; the heavy base64 image is excluded here and read
# separately only for the surviving pages.
_HIT_PAYLOAD_INCLUDE = [
    "space_key",
    "page_id",
    "page_title",
    "page_url",
    "attachment_id",
    "attachment_name",
    "content_kind",
    "document_name",
    "breadcrumb",
    "text",
    "page_number",
    "page_count",
    "part_index",
]

_HEADER_TEXT_LENGTH_CAP = 200


class RetrievalScope:
    """Optional scope of a document retrieval: space, page and/or document-name pattern."""

    def __init__(
        self,
        space_key: str | None = None,
        page_id: str | None = None,
        document_name_pattern: str | None = None,
    ):
        self.space_key = space_key
        self.page_id = page_id
        self.document_name_pattern = document_name_pattern


def _header(part: DocumentPagePart) -> str:
    """The header text part: reconciliation chain, or breadcrumb and URL."""
    if part.content_kind == "attachment":
        return f"Reference documentation: {part.breadcrumb}"
    header = f"Reference documentation: {part.breadcrumb}"
    if part.page_url:
        header = f"{header} ({part.page_url})"
    return header


def _scope_filter(scope: RetrievalScope | None, skip_name_pattern: bool = False) -> models.Filter | None:
    """Exact payload filters for the scope; the name pattern is resolved separately."""
    if scope is None:
        return None
    must = []
    if scope.space_key:
        must.append(models.FieldCondition(key="space_key", match=models.MatchValue(value=scope.space_key)))
    if scope.page_id:
        must.append(models.FieldCondition(key="page_id", match=models.MatchValue(value=scope.page_id)))
    return models.Filter(must=must) if must else None


async def _matching_document_names(
    documents_db: VectorDbService, scope: RetrievalScope, pattern
) -> list[str] | None:
    """Distinct document names under the scope filters matching the pattern.

    Returns None when there is no pattern, so the caller knows to skip this step.
    """
    names: list[str] = []
    offset = None
    while True:
        points, next_offset = await documents_db.client.scroll(
            collection_name=documents_db.collection_name,
            scroll_filter=_scope_filter(scope),
            limit=1000,
            offset=offset,
            with_payload=models.PayloadSelectorInclude(include=["document_name"]),
            with_vectors=False,
        )
        names.extend(p.payload["document_name"] for p in points if p.payload and p.payload.get("document_name"))
        if next_offset is None:
            break
        offset = next_offset
    matched = sorted({name for name in names if pattern.search(name)})
    logger.info(f"Document-name pattern matched {len(matched)} of {len(names)} distinct name(s).")
    return matched


class RetrievedPage:
    """One retrieved page: its best-ranked part plus the image fetched for it."""

    def __init__(self, part: DocumentPagePart, image: bytes | None):
        self.part = part
        self.image = image


async def retrieve_documents(
    documents_db: VectorDbService,
    query_text: str,
    scope: RetrievalScope | None = None,
    limit: int | None = None,
) -> list[RetrievedPage]:
    """Runs one scoped hybrid retrieval and returns the surviving pages assembled.

    Raises when the embedding service or Qdrant fails; the caller decides how a
    runtime failure affects the overall flow (the review fails).
    """
    limit = limit or config.QdrantConfig.MAX_RESULTS
    pattern = None
    if scope and scope.document_name_pattern:
        pattern = utils.compile_name_pattern(scope.document_name_pattern)

    query_filter = _scope_filter(scope)
    if pattern is not None:
        matched_names = await _matching_document_names(documents_db, scope, pattern)
        if not matched_names:
            logger.info("No document names match the pattern; returning an empty result without a query.")
            return []
        name_condition = models.FieldCondition(key="document_name", match=models.MatchAny(any=matched_names))
        query_filter = (
            models.Filter(must=[*(query_filter.must if query_filter else []), name_condition]) if query_filter else models.Filter(must=[name_condition])
        )

    hits = await documents_db.hybrid_search(
        query_text,
        limit=limit,
        score_threshold=config.QdrantConfig.MIN_SIMILARITY_SCORE,
        query_filter=query_filter,
        with_payload=models.PayloadSelectorInclude(include=_HIT_PAYLOAD_INCLUDE),
    )
    if not hits:
        return []

    # Group per page identity; the best (first = best-ranked) hit per page wins.
    best_per_page: dict[tuple, models.ScoredPoint] = {}
    order: list[tuple] = []
    for hit in hits:
        payload = hit.payload or {}
        key = (
            (payload.get("attachment_id"), payload.get("page_number"))
            if payload.get("content_kind") == "attachment"
            else (payload.get("page_id"), "body")
        )
        if key not in best_per_page:
            best_per_page[key] = hit
            order.append(key)

    pages: list[RetrievedPage] = []
    for key in order[:limit]:
        hit = best_per_page[key]
        payload = hit.payload or {}
        part = DocumentPagePart.model_validate(payload)
        image = await _fetch_page_image(documents_db, part)
        pages.append(RetrievedPage(part, image))
    return pages


async def _fetch_page_image(documents_db: VectorDbService, part: DocumentPagePart) -> bytes | None:
    """Fetches the page image by the deterministic part-0 ID of an attachment page."""
    if part.content_kind != "attachment":
        return None
    part0 = part.model_copy(update={"part_index": 0})
    try:
        records = await documents_db.retrieve([part0.get_vector_id()])
    except Exception:
        logger.exception(f"Failed to fetch the page image of {part.breadcrumb}.")
        raise
    if not records or not records[0].payload:
        return None
    image = records[0].payload.get("image")
    if not image:
        return None
    import base64

    return base64.b64decode(image)


def assemble_retrieved_parts(pages: list[RetrievedPage]) -> list[str | BinaryContent]:
    """Assembles retrieved pages into review-ready message parts (plan §9).

    Each page contributes a header text part plus exactly one content part: the
    page image (identified by attachment name and page number) when present,
    otherwise the page text; a page with neither is omitted.
    """
    parts: list[str | BinaryContent] = []
    for page in pages:
        part = page.part
        parts.append(_header(part))
        if page.image is not None:
            parts.append(
                BinaryContent(
                    data=page.image,
                    media_type="image/png",
                    identifier=f"{part.attachment_name} page {part.page_number}",
                )
            )
        elif part.text:
            parts.append(part.text)
    return parts

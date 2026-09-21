# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Scoped hybrid retrieval over the per-source document collections.

One retrieval turns a query text plus an optional scope (Confluence: space key, page ID;
SharePoint: drive ID, folder path; shared: document-name pattern) into assembled,
review-ready documentation parts from every enabled source:

1. Every enabled source is queried **concurrently** against its own collection, and every
   query pins the ``source`` payload discriminator, so a document stranded in the wrong
   collection can never surface.
2. Scope fields of the other source are ignored: Confluence space/page apply only to the
   Confluence query, SharePoint drive/folder only to the SharePoint query.
3. Qdrant has no regex filter, so a document-name pattern is resolved first per source: the
   distinct document names under the remaining filters are scrolled, matched client-side and
   queried with an exact MatchAny filter. No match means an empty result for that source
   without running the query at all.
4. The shared hybrid query runs with the page image excluded from the payload; the configured
   minimum similarity score reaches the dense prefetch.
5. Hits are grouped per page (an attachment page is one attachment ID + page number; a
   page-body chunk stands alone) and the best rank per page wins.
6. The per-source page lists are merged by rank interleaving up to the page bound: fused
   scores are not comparable across collections, but ranks are.
7. The page image of each surviving page is fetched by reconstructing its deterministic
   part-0 point ID.

A source that fails at runtime is logged and skipped; the result names it as unavailable so
the review can say so.
"""

import asyncio
import base64
from dataclasses import dataclass

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
    "source",
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

CONFLUENCE_SOURCE = "confluence"
SHAREPOINT_SOURCE = "sharepoint"


@dataclass(frozen=True, slots=True)
class RetrievalScope:
    """Optional scope of a document retrieval.

    There is no ``source`` field: the sources are queried independently, and each source
    ignores the scope fields that belong to the other one.
    """

    space_key: str | None = None
    page_id: str | None = None
    document_name_pattern: str | None = None
    drive_id: str | None = None
    folder_path: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Merged pages of one retrieval plus the sources that failed at runtime."""

    pages: list["RetrievedPage"]
    unavailable_sources: list[str]


def _header(part: DocumentPagePart) -> str:
    """The header text part: the breadcrumb, plus the page URL where a page body has one."""
    header = f"Reference documentation: {part.breadcrumb}"
    if part.content_kind != "attachment" and part.page_url:
        header = f"{header} ({part.page_url})"
    return header


def _enabled_sources() -> list[str]:
    """The document sources whose retrieval switch is on."""
    sources = []
    if config.DocumentRagConfig.CONFLUENCE_RETRIEVAL_ENABLED:
        sources.append(CONFLUENCE_SOURCE)
    if config.DocumentRagConfig.SHAREPOINT_RETRIEVAL_ENABLED:
        sources.append(SHAREPOINT_SOURCE)
    return sources


def _scope_filter(scope: RetrievalScope | None, source: str) -> models.Filter | None:
    """Exact payload filters for one source's scope: its own fields, plus the discriminator.

    The document-name pattern is resolved separately, so it is not part of this filter.
    """
    must = [models.FieldCondition(key="source", match=models.MatchValue(value=source))]
    if scope:
        if source == CONFLUENCE_SOURCE:
            if scope.space_key:
                must.append(models.FieldCondition(key="space_key", match=models.MatchValue(value=scope.space_key)))
            if scope.page_id:
                must.append(models.FieldCondition(key="page_id", match=models.MatchValue(value=scope.page_id)))
        elif source == SHAREPOINT_SOURCE:
            if scope.drive_id:
                must.append(models.FieldCondition(key="drive_id", match=models.MatchValue(value=scope.drive_id)))
            if scope.folder_path:
                must.append(models.FieldCondition(key="folder_path", match=models.MatchValue(value=scope.folder_path)))
    return models.Filter(must=must)


async def _matching_document_names(
    documents_db: VectorDbService, scope: RetrievalScope | None, source: str, pattern
) -> list[str]:
    """Distinct document names under one source's scope filters matching the pattern."""
    points = await documents_db.scroll_points(_scope_filter(scope, source), ["document_name"])
    names = [p.payload["document_name"] for p in points if p.payload and p.payload.get("document_name")]
    matched = sorted({name for name in names if pattern.search(name)})
    logger.info("Document-name pattern matched %s of %s distinct %s name(s).", len(matched), len(names), source)
    return matched


@dataclass(slots=True)
class RetrievedPage:
    """One retrieved page: its best-ranked part plus the image fetched for it."""

    part: DocumentPagePart
    image: bytes | None


async def retrieve_documents(
    documents_db: VectorDbService,
    query_text: str,
    scope: RetrievalScope | None = None,
    limit: int | None = None,
    sharepoint_db: VectorDbService | None = None,
) -> RetrievalResult:
    """Queries every enabled source concurrently and merges the surviving pages.

    ``documents_db`` is the Confluence collection service; ``sharepoint_db`` the SharePoint
    one. A failing source is logged, skipped and reported as unavailable, so one broken
    source never fails the review on its own. It only raises when *every* enabled source
    fails, so the caller can distinguish "no results" from "the store is down".
    """
    limit = limit or config.QdrantConfig.MAX_RESULTS
    sources = _enabled_sources()
    if not sources:
        logger.warning("No document source has retrieval enabled; returning no reference documentation.")
        return RetrievalResult([], [])

    results = await asyncio.gather(
        *[
            _retrieve_source(
                documents_db if source == CONFLUENCE_SOURCE else sharepoint_db,
                query_text,
                scope,
                limit,
                source,
            )
            for source in sources
        ],
        return_exceptions=True,
    )

    merged_lists: list[list[RetrievedPage]] = []
    unavailable: list[str] = []
    failed = 0
    for source, result in zip(sources, results, strict=True):
        if isinstance(result, BaseException):
            # gather(return_exceptions=True) returns the exception instead of raising it, so
            # there is no active exception for logger.exception to read a traceback from.
            logger.error(
                "%s document retrieval failed; the source is unavailable for this review.",
                source,
                exc_info=result,
            )
            unavailable.append(source)
            failed += 1
        else:
            merged_lists.append(result)
    if failed == len(sources):
        raise RuntimeError(f"All document sources failed: {', '.join(unavailable)}.")

    interleaved = _interleave(merged_lists)
    pages = interleaved[:limit]
    for source_db, source in ((documents_db, CONFLUENCE_SOURCE), (sharepoint_db, SHAREPOINT_SOURCE)):
        await _attach_page_images(source_db, [page for page in pages if page.part.source == source])
    return RetrievalResult(pages, unavailable)


async def _retrieve_source(
    documents_db: VectorDbService | None,
    query_text: str,
    scope: RetrievalScope | None,
    limit: int,
    source: str,
) -> list[RetrievedPage]:
    """One source's scoped hybrid retrieval, returning that source's pages in rank order."""
    if documents_db is None:
        raise RuntimeError(f"The {source} collection service is not configured even though its retrieval is enabled.")
    pattern = None
    if scope and scope.document_name_pattern:
        pattern = utils.compile_name_pattern(scope.document_name_pattern)

    query_filter = _scope_filter(scope, source)
    if pattern is not None:
        matched_names = await _matching_document_names(documents_db, scope, source, pattern)
        if not matched_names:
            logger.info("No %s document names match the pattern; returning an empty result without a query.", source)
            return []
        name_condition = models.FieldCondition(key="document_name", match=models.MatchAny(any=matched_names))
        query_filter = models.Filter(must=[*query_filter.must, name_condition])

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
            else (payload.get("page_id") or payload.get("document_name"), "body")
        )
        if key not in best_per_page:
            best_per_page[key] = hit
            order.append(key)

    pages: list[RetrievedPage] = []
    for key in order[:limit]:
        hit = best_per_page[key]
        part = DocumentPagePart.model_validate(hit.payload or {})
        pages.append(RetrievedPage(part, None))
    return pages


def _interleave(source_pages: list[list[RetrievedPage]]) -> list[RetrievedPage]:
    """Rank-interleaves the per-source page lists: first each source's best page, then the second..."""
    merged: list[RetrievedPage] = []
    for rank in range(max((len(pages) for pages in source_pages), default=0)):
        for pages in source_pages:
            if rank < len(pages):
                merged.append(pages[rank])
    return merged


async def _attach_page_images(documents_db: VectorDbService | None, pages: list[RetrievedPage]) -> None:
    """Fetches one source's page images in a single retrieve, by the part-0 IDs of its attachment pages.

    A failure here leaves the images unset rather than propagating: the module's contract is
    that a broken source never fails the whole review, and a page without its image falls back
    to its text in :func:`assemble_retrieved_parts`.
    """
    attachment_pages = [page for page in pages if page.part.content_kind == "attachment"]
    if documents_db is None or not attachment_pages:
        return
    image_ids = [page.part.model_copy(update={"part_index": 0}).get_vector_id() for page in attachment_pages]
    try:
        records = await documents_db.retrieve(image_ids)
        images = {str(record.id): (record.payload or {}).get("image") for record in records}
        for page, image_id in zip(attachment_pages, image_ids, strict=True):
            image = images.get(image_id)
            if image:
                page.image = base64.b64decode(image)
    except Exception:
        logger.exception("Failed to fetch %s page image(s); the pages fall back to their text.", len(image_ids))


def assemble_retrieved_parts(pages: list[RetrievedPage]) -> list[str | BinaryContent]:
    """Assembles retrieved pages into review-ready message parts.

    Each page contributes a header text part plus exactly one content part: the
    page image (identified by attachment name and page number) when present,
    otherwise the page text; a page with neither is omitted, header included.
    """
    parts: list[str | BinaryContent] = []
    for page in pages:
        part = page.part
        if page.image is not None:
            content: str | BinaryContent = BinaryContent(
                data=page.image,
                media_type="image/png",
                identifier=f"{part.attachment_name} page {part.page_number}",
            )
        elif part.text:
            content = part.text
        else:
            continue
        parts.append(_header(part))
        parts.append(content)
    return parts

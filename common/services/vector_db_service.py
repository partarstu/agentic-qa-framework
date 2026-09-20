# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
import random
import time
import uuid

import httpx
from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

import config
from common import utils
from common.models import VectorizableBaseModel

logger = utils.get_logger("vector_db_service")

# Named vectors on every collection this service manages: dense + learned-sparse.
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"

# Gateway statuses the database sits behind (a serverless front end) which are worth
# retrying; every other UnexpectedResponse, 4xx included, propagates untouched.
_QDRANT_RETRYABLE_STATUSES = frozenset({502, 503, 504})
_QDRANT_RETRY_ATTEMPTS = 3


# Payload fields indexed per collection kind after creation; matching is by collection name from configuration.
_DOCUMENTS_INDEXED_FIELDS = {
    "source": models.PayloadSchemaType.KEYWORD,  # every document query pins the source discriminator
    "space_key": models.PayloadSchemaType.KEYWORD,
    "page_id": models.PayloadSchemaType.KEYWORD,
    "attachment_id": models.PayloadSchemaType.KEYWORD,
    "document_name": models.PayloadSchemaType.KEYWORD,
    "content_kind": models.PayloadSchemaType.KEYWORD,
}
_SHAREPOINT_INDEXED_FIELDS = {
    "source": models.PayloadSchemaType.KEYWORD,
    "drive_id": models.PayloadSchemaType.KEYWORD,
    "folder_path": models.PayloadSchemaType.KEYWORD,
    "attachment_id": models.PayloadSchemaType.KEYWORD,
    "document_name": models.PayloadSchemaType.KEYWORD,
    "content_kind": models.PayloadSchemaType.KEYWORD,
}
_JIRA_INDEXED_FIELDS = {
    "project_key": models.PayloadSchemaType.KEYWORD,
    "issue_type": models.PayloadSchemaType.KEYWORD,
    "status": models.PayloadSchemaType.KEYWORD,
}
_METADATA_INDEXED_FIELDS = {
    "scope": models.PayloadSchemaType.KEYWORD,
    "kind": models.PayloadSchemaType.KEYWORD,
}
_TEST_CASES_INDEXED_FIELDS = {
    "project_key": models.PayloadSchemaType.KEYWORD,
    "test_case_key": models.PayloadSchemaType.KEYWORD,
}


async def _retry_qdrant(operation: str, run):
    """Runs one asynchronous vector-database call with bounded retries.

    Only genuine transport failures (``ResponseHandlingException`` wraps connection errors
    and timeouts) and the gateway statuses 502/503/504 are retried, with exponential
    back-off and jitter. Every operation is idempotent (deterministic ids), so a retry
    cannot duplicate data. Each retry logs the operation, the reason and the delay.
    """
    for attempt in range(_QDRANT_RETRY_ATTEMPTS):
        try:
            return await run()
        except ResponseHandlingException as e:
            error, reason, retryable = e, type(e.__cause__).__name__ if e.__cause__ else type(e).__name__, True
        except UnexpectedResponse as e:
            error, reason, retryable = e, f"HTTP {e.status_code}", e.status_code in _QDRANT_RETRYABLE_STATUSES
        if not retryable or attempt == _QDRANT_RETRY_ATTEMPTS - 1:
            raise error
        delay = min(2**attempt + random.uniform(0, 0.5), 30)
        logger.warning(
            "Vector-database %s failed (attempt %s/%s, reason: %s); retrying in %.1fs",
            operation,
            attempt + 1,
            _QDRANT_RETRY_ATTEMPTS,
            reason,
            delay,
        )
        await asyncio.sleep(delay)


class VectorCollectionSchemaError(RuntimeError):
    """An existing collection's vector configuration doesn't match the active embedding mode."""


def _schema_problems(params: models.CollectionParams, dense_size: int) -> list[str]:
    """The missing or incompatible vectors of a collection, compared with the active embedding mode."""
    problems: list[str] = []
    named_vectors = params.vectors if isinstance(params.vectors, dict) else {}
    dense = named_vectors.get(DENSE_VECTOR_NAME)
    if dense is None:
        problems.append(f"the named dense vector '{DENSE_VECTOR_NAME}' is missing")
    else:
        if dense.size != dense_size:
            problems.append(f"the dense vector has size {dense.size} instead of {dense_size}")
        if dense.distance != models.Distance.COSINE:
            problems.append(f"the dense vector uses {dense.distance.value} distance instead of cosine")
    if SPARSE_VECTOR_NAME not in (params.sparse_vectors or {}):
        problems.append(f"the named sparse vector '{SPARSE_VECTOR_NAME}' is missing")
    return problems


def _record_uuid(record_id: str) -> str:
    """Deterministic UUID for a metadata record, derived from its ID.

    Qdrant's local mode validates string IDs as UUIDs; deriving one from the record ID
    keeps records addressable across processes and safe in local mode alike.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"quaia:{record_id}"))


class VectorDbService:
    def __init__(
        self,
        collection_name: str,
        metadata_collection_name: str | None = None,
        metadata_db: "VectorDbService | None" = None,
    ):
        self.collection_name = collection_name
        # QDRANT_URL is authoritative and includes the port (or relies on the scheme default).
        # port=None keeps the client from appending its own default (qdrant-client#394).
        # check_compatibility=False skips the client's construction-time server-version probe:
        # a blocking HTTP GET that would run on the event loop of whoever constructs the
        # service (the dashboard constructs one per request) and stall it for as long as the
        # server is slow to answer. Schema mismatches surface through the validation.
        self.client = AsyncQdrantClient(
            url=config.QdrantConfig.URL,
            port=None,
            api_key=config.QdrantConfig.API_KEY,
            timeout=config.QdrantConfig.TIMEOUT_SECONDS,
            check_compatibility=False,
        )
        self.embedding_service_url = config.QdrantConfig.EMBEDDING_SERVICE_URL
        if not self.embedding_service_url:
            logger.warning("EMBEDDING_SERVICE_URL is not configured. Vector operations requiring embeddings will fail.")
        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.QdrantConfig.EMBEDDING_SERVICE_TIMEOUT_SECONDS)
        )
        self._embedding_max_retries = config.QdrantConfig.EMBEDDING_SERVICE_MAX_RETRIES
        self._embedding_retry_backoff_cap = config.QdrantConfig.EMBEDDING_SERVICE_RETRY_BACKOFF_CAP_SECONDS
        # Collections whose writes must not go through the embedding service (locks, sync state,
        # fingerprints, model identity): records are stored without vectors. A shared instance
        # can be passed in so callers that also hold their own metadata service don't duplicate
        # clients against the same collection.
        self._metadata_db = metadata_db or (
            VectorDbService(metadata_collection_name)
            if metadata_collection_name and metadata_collection_name != collection_name
            else None
        )
        self._upsert_batch_size = config.QdrantConfig.UPSERT_BATCH_SIZE
        # One ensure per collection per service instance is enough: index creation is
        # idempotent, and re-listing collections on every upsert/query wastes a round trip.
        self._ensured = False
        # The existing collection's vector schema is validated once per instance, at first use.
        self._schema_validated = False

    async def close(self):
        """Close the embedding HTTP client and Qdrant connection pool."""
        await self._http_client.aclose()
        await self.client.close()
        if self._metadata_db is not None:
            await self._metadata_db.close()

    async def _embed_texts(self, texts: list[str], query: bool = False):
        """Embeds texts through the embedding service, using the query endpoint only when ``query`` is set.

        Returns:
            A tuple (embeddings, model), where each embedding is a (dense vector, sparse indices,
            sparse values) tuple.
        """
        if not self.embedding_service_url:
            raise ValueError("EMBEDDING_SERVICE_URL is not configured.")

        endpoint = "/embed-query-text" if query else "/embed-document-text"
        max_retries = self._embedding_max_retries
        logger.info("Calling embedding service%s (%s text(s))...", endpoint, len(texts))
        start = time.monotonic()

        for attempt in range(max_retries):
            try:
                headers = {"X-API-Key": config.INTERNAL_SERVICE_API_KEY} if config.INTERNAL_SERVICE_API_KEY else None
                response = await self._http_client.post(
                    f"{self.embedding_service_url}{endpoint}", json={"texts": texts}, headers=headers
                )
                response.raise_for_status()
                body = response.json()
                embeddings = [
                    (item["dense"], item["sparse"]["indices"], item["sparse"]["values"]) for item in body["embeddings"]
                ]
                logger.info(f"Embedding service call completed in {time.monotonic() - start:.3f}s")
                return embeddings, body.get("model")
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt == max_retries - 1:
                    logger.exception(
                        f"Failed to call embedding service at {self.embedding_service_url} after {max_retries} attempts."
                    )
                    raise
                wait_time = min(2**attempt, self._embedding_retry_backoff_cap)
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries} failed calling embedding service: {e}. Retrying in {wait_time}s..."
                )
                await asyncio.sleep(wait_time)
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status not in (429, 502, 503, 504) or attempt == max_retries - 1:
                    logger.exception("HTTP error from embedding service: %s - %s", status, e.response.text)
                    raise
                retry_after = e.response.headers.get("Retry-After")
                wait_time = (
                    min(float(retry_after), self._embedding_retry_backoff_cap)
                    if retry_after
                    else min(2**attempt, self._embedding_retry_backoff_cap)
                )
                logger.warning(
                    "Attempt %s/%s got HTTP %s from the embedding service; retrying in %.1fs",
                    attempt + 1,
                    max_retries,
                    status,
                    wait_time,
                )
                await asyncio.sleep(wait_time)
            except Exception:
                logger.exception("Error calling embedding service")
                raise
        # Reachable when the retry budget is configured as 0: callers unpack the result,
        # so failure is signalled by raising rather than by returning None.
        raise RuntimeError(f"The embedding service was not called: {max_retries} retries are configured.")

    async def _get_embedding(self, text: str) -> list[float]:
        """Dense embedding of one text, for call sites that don't use the sparse vector yet."""
        embeddings, _ = await self._embed_texts([text])
        return embeddings[0][0]

    async def _collection_exists(self) -> bool:
        """Checks collection existence by listing all collections to avoid the /exists endpoint's empty-body issue."""
        collections = await self.client.get_collections()
        return any(c.name == self.collection_name for c in collections.collections)

    async def ensure_collection(self):
        """Creates the collection with the hybrid schema (named dense + sparse vectors).

        The dense size is detected from the embedding service. The model that produced
        the vectors is recorded in the metadata collection, and later writes/queries
        refuse to run with a different model. An existing collection's vector schema is
        validated against the active embedding mode first. Payload indexes are (re-)ensured
        idempotently, so a collection created before its indexes existed still gets
        them on the next ensure.

        Raises:
            VectorCollectionSchemaError: When the existing collection's vectors don't match
                the active embedding mode.
        """
        if self._ensured:
            return
        if await self._collection_exists():
            if not self._schema_validated:
                embeddings, _ = await self._embed_texts(["test"])
                await self._validate_schema(len(embeddings[0][0]))
            await self._ensure_payload_indexes()
            self._ensured = True
            return
        embeddings, model = await self._embed_texts(["test"])
        vector_size = len(embeddings[0][0])

        try:
            await self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    DENSE_VECTOR_NAME: models.VectorParams(size=vector_size, distance=models.Distance.COSINE)
                },
                sparse_vectors_config={SPARSE_VECTOR_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)},
            )
            logger.info(
                "Created collection %s with named dense(%s) + sparse vectors.", self.collection_name, vector_size
            )
        except Exception as e:
            # Handle race condition where collection is created concurrently
            if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                logger.info("Collection %s already exists (race condition handled).", self.collection_name)
            else:
                raise e

        await self._ensure_payload_indexes()

        if self._metadata_db is not None:
            await self._metadata_db._store_model_identity(self.collection_name, model)
        self._schema_validated = True
        self._ensured = True

    async def _validate_schema(self, dense_size: int) -> None:
        """Fails with an actionable error when the collection's vectors don't fit the active embedding mode.

        The active mode is a named dense vector of the embedding model's size with cosine
        distance plus a named sparse vector. Without this check a collection created by an
        older schema (e.g. a single unnamed dense vector) fails with an opaque error deep
        inside the first write or query.

        Raises:
            VectorCollectionSchemaError: Naming the collection, the expected mode and every
                missing or incompatible vector.
        """
        if self._schema_validated:
            return
        info = await _retry_qdrant(
            f"schema read of {self.collection_name}", lambda: self.client.get_collection(self.collection_name)
        )
        problems = _schema_problems(info.config.params, dense_size)
        if problems:
            raise VectorCollectionSchemaError(
                f"Collection '{self.collection_name}' does not match the active embedding mode (named dense vector "
                f"'{DENSE_VECTOR_NAME}' of size {dense_size} with cosine distance, and named sparse vector "
                f"'{SPARSE_VECTOR_NAME}'): {'; '.join(problems)}. Recreate the collection and resync its source "
                f"to migrate (see 'Migrating a vector collection' in the README)."
            )
        self._schema_validated = True

    def _indexed_fields(self) -> dict[str, models.PayloadSchemaType]:
        """The payload fields this collection should have indexes on, by collection name."""
        if self.collection_name == config.QdrantConfig.TICKETS_COLLECTION_NAME:
            return _JIRA_INDEXED_FIELDS
        if self.collection_name == config.QdrantConfig.METADATA_COLLECTION_NAME:
            return _METADATA_INDEXED_FIELDS
        if self.collection_name == config.DocumentRagConfig.DOCUMENTS_COLLECTION_NAME:
            return _DOCUMENTS_INDEXED_FIELDS
        if self.collection_name == config.QdrantConfig.SHAREPOINT_COLLECTION_NAME:
            return _SHAREPOINT_INDEXED_FIELDS
        if self.collection_name == config.QdrantConfig.TEST_CASES_COLLECTION_NAME:
            return _TEST_CASES_INDEXED_FIELDS
        return {}

    async def _ensure_payload_indexes(self) -> None:
        """Creates the plan's payload indexes for this collection; idempotent.

        A concurrent creation raises an 'already exists' error, which is tolerated.
        """
        for field_name, field_type in self._indexed_fields().items():
            try:
                await self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_schema=field_type,
                )
                logger.info("Created payload index on %s in %s.", field_name, self.collection_name)
            except Exception as e:
                if "already exists" in str(e).lower():
                    logger.info("Payload index on %s in %s already exists.", field_name, self.collection_name)
                else:
                    raise

    async def _verify_model_identity(self, model: str) -> None:
        """Fails with a clear error when the collection's vectors come from a different model.

        Without this check, switching the embedding model would silently mix vector
        spaces in one collection. Collections created before this check existed are
        treated as unclaimed and claimed by the first writer.
        """
        if self._metadata_db is None:
            return
        stored = await self._metadata_db._get_model_identity(self.collection_name)
        if stored is not None and stored != model:
            raise RuntimeError(
                f"Collection '{self.collection_name}' holds vectors from model '{stored}', "
                f"but the embedding service now uses '{model}'. Recreate the collection and "
                f"reset its sync state to re-ingest."
            )
        if stored is None:
            await self._metadata_db._store_model_identity(self.collection_name, model)

    def _model_identity_id(self, collection_name: str) -> str:
        # Qdrant accepts only unsigned integers and UUIDs as point IDs.
        return _record_uuid(f"model-identity-{collection_name}")

    async def _store_model_identity(self, collection_name: str, model: str) -> None:
        """Record which model produced a collection's vectors (part of the metadata collection)."""
        await _retry_qdrant(
            f"model-identity write for {collection_name}",
            lambda: self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    models.PointStruct(
                        id=self._model_identity_id(collection_name),
                        vector={},
                        payload={"kind": "model-identity", "collection": collection_name, "model": model},
                    )
                ],
            ),
        )

    async def _get_model_identity(self, collection_name: str) -> str | None:
        """Read the recorded model for a collection, or None when it isn't recorded."""
        points = await _retry_qdrant(
            f"model-identity read for {collection_name}",
            lambda: self.client.retrieve(
                collection_name=self.collection_name,
                ids=[self._model_identity_id(collection_name)],
            ),
        )
        if points and points[0].payload:
            return points[0].payload.get("model")
        return None

    async def hybrid_search(
        self,
        query_text: str,
        limit: int = 5,
        score_threshold: float | None = None,
        query_filter: models.Filter | None = None,
        with_payload: bool | dict | models.PayloadSelector | None = True,
    ) -> list[models.ScoredPoint]:
        """Hybrid (dense + learned-sparse) search fused with RRF.

        1. The query is embedded once (dense + sparse).
        2. One prefetch per named vector runs with the same filter; each prefetch limit
           covers the final limit.
        3. The similarity threshold applies to the dense prefetch only: fused RRF scores
           are rank-based, so the configured thresholds keep their meaning on the dense
           branch.
        4. Prefetches are fused with RRF.
        """
        logger.info("Starting hybrid search in '%s' (limit %s)...", self.collection_name, limit)
        try:
            embeddings, model = await self._embed_texts([query_text], query=True)
            dense, sparse_indices, sparse_values = embeddings[0]
            await self._validate_schema(len(dense))
            await self._verify_model_identity(model)

            dense_prefetch = models.Prefetch(
                query=dense,
                using=DENSE_VECTOR_NAME,
                limit=limit,
                filter=query_filter,
                score_threshold=score_threshold,
            )
            sparse_prefetch = models.Prefetch(
                query=models.SparseVector(indices=sparse_indices, values=sparse_values),
                using=SPARSE_VECTOR_NAME,
                limit=limit,
                filter=query_filter,
            )
            response = await _retry_qdrant(
                f"hybrid search in {self.collection_name}",
                lambda: self.client.query_points(
                    collection_name=self.collection_name,
                    prefetch=[dense_prefetch, sparse_prefetch],
                    query=models.FusionQuery(fusion=models.Fusion.RRF),
                    limit=limit,
                    with_payload=with_payload,
                ),
            )
            return response.points
        except UnexpectedResponse as exc:
            if exc.status_code == 404:
                logger.warning("Collection %s does not exist yet in DB.", self.collection_name)
                return []
            raise
        except Exception:
            logger.exception("Error querying Vector DB")
            raise

    async def upsert(self, data: VectorizableBaseModel, ensure: bool = True):
        """Upserts one record with named dense + sparse vectors produced in one embedding pass."""
        try:
            if ensure:
                await self.ensure_collection()
            text = data.get_embedding_content()
            payload = data.model_dump()
            point_id = data.get_vector_id()

            embeddings, model = await self._embed_texts([text])
            await self._verify_model_identity(model)
            dense, sparse_indices, sparse_values = embeddings[0]
            point = models.PointStruct(
                id=point_id,
                vector={
                    DENSE_VECTOR_NAME: dense,
                    SPARSE_VECTOR_NAME: models.SparseVector(indices=sparse_indices, values=sparse_values),
                },
                payload=payload,
            )
            await _retry_qdrant(
                f"upsert into {self.collection_name}",
                lambda: self.client.upsert(collection_name=self.collection_name, points=[point]),
            )
            logger.info(f"Upserted document with ID {point_id} to collection {self.collection_name}")
        except Exception:
            logger.exception("Error upserting to Vector DB")
            raise

    async def upsert_batch(self, data: list[VectorizableBaseModel], ensure: bool = True):
        """Upserts many records in batches, one embedding call per batch.

        Batches respect the request size limit; the embedding service is called once per
        batch so a large sync run stays within its input limits.
        """
        try:
            if not data:
                return
            if ensure:
                await self.ensure_collection()
            for start in range(0, len(data), self._upsert_batch_size):
                batch = data[start : start + self._upsert_batch_size]
                texts = [item.get_embedding_content() for item in batch]
                embeddings, model = await self._embed_texts(texts)
                await self._verify_model_identity(model)
                points = []
                for item, (dense, sparse_indices, sparse_values) in zip(batch, embeddings, strict=True):
                    points.append(
                        models.PointStruct(
                            id=item.get_vector_id(),
                            vector={
                                DENSE_VECTOR_NAME: dense,
                                SPARSE_VECTOR_NAME: models.SparseVector(indices=sparse_indices, values=sparse_values),
                            },
                            payload=item.model_dump(),
                        )
                    )
                await _retry_qdrant(
                    f"upsert into {self.collection_name}",
                    lambda points=points: self.client.upsert(collection_name=self.collection_name, points=points),
                )
                logger.info("Upserted batch of %s point(s) to collection %s", len(points), self.collection_name)
        except Exception:
            logger.exception("Error batch-upserting to Vector DB")
            raise

    async def retrieve(
        self,
        point_ids: list[int | str],
        with_payload: bool | dict | models.PayloadSelector | None = True,
    ) -> list[models.Record]:
        """Retrieve points by their IDs from the collection.

        Raises:
            Exception: If retrieval from Vector DB fails.
        """
        try:
            await self.ensure_collection()
            return await _retry_qdrant(
                f"retrieve from {self.collection_name}",
                lambda: self.client.retrieve(
                    collection_name=self.collection_name,
                    ids=point_ids,
                    with_payload=with_payload,
                ),
            )
        except Exception:
            logger.exception("Error retrieving from Vector DB")
            raise

    async def delete(self, point_ids: list[int | str]):
        """Delete points by their IDs from the collection.

        Raises:
            Exception: If deletion from Vector DB fails.
        """
        try:
            await _retry_qdrant(
                f"delete from {self.collection_name}",
                lambda: self.client.delete(
                    collection_name=self.collection_name, points_selector=models.PointIdsList(points=point_ids)
                ),
            )
            logger.info(f"Deleted documents with IDs {point_ids} from collection {self.collection_name}")
        except Exception:
            logger.exception("Error deleting from Vector DB")
            raise

    async def has_points(self, scope_filter: models.Filter) -> bool:
        """Whether at least one point matches the filter; False when the collection doesn't exist."""
        if not await self._collection_exists():
            return False
        points, _ = await _retry_qdrant(
            f"existence scroll in {self.collection_name}",
            lambda: self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=scope_filter,
                limit=1,
                with_payload=False,
                with_vectors=False,
            ),
        )
        return bool(points)

    async def delete_by_filter(self, scope_filter: models.Filter):
        """Delete every point matching the filter (reconciliation of removed items)."""
        try:
            await _retry_qdrant(
                f"filtered delete from {self.collection_name}",
                lambda: self.client.delete(
                    collection_name=self.collection_name, points_selector=models.FilterSelector(filter=scope_filter)
                ),
            )
            logger.info("Deleted points matching filter from collection %s", self.collection_name)
        except Exception:
            logger.exception("Error deleting by filter from Vector DB")
            raise

    async def set_payload(
        self, payload: dict, point_ids: list[int | str] | None = None, scope_filter: models.Filter | None = None
    ):
        """Payload-only update for metadata changes without re-embedding."""
        try:
            selector = (
                models.PointIdsList(points=point_ids)
                if point_ids is not None
                else models.FilterSelector(filter=scope_filter)
            )
            await _retry_qdrant(
                f"payload update in {self.collection_name}",
                lambda: self.client.set_payload(
                    collection_name=self.collection_name,
                    payload=payload,
                    points=selector,
                ),
            )
            logger.info(
                "Updated payload on %s point(s) in %s",
                len(point_ids) if point_ids else "filtered",
                self.collection_name,
            )
        except Exception:
            logger.exception("Error updating payload in Vector DB")
            raise

    async def scroll_points(
        self, scroll_filter: models.Filter, payload_fields: list[str] | None = None
    ) -> list[models.Record]:
        """Scrolls every point matching a filter, page by page, with the selected payload fields.

        The one scroll implementation for callers that need a payload-field subset, so the
        pagination loop isn't re-implemented against the client on each of them.
        """
        try:
            records: list[models.Record] = []
            offset = None
            selector = models.PayloadSelectorInclude(include=payload_fields) if payload_fields else True
            while True:
                points, next_offset = await _retry_qdrant(
                    "scroll",
                    lambda current_offset=offset: self.client.scroll(
                        collection_name=self.collection_name,
                        scroll_filter=scroll_filter,
                        limit=1000,
                        offset=current_offset,
                        with_payload=selector,
                        with_vectors=False,
                    ),
                )
                records.extend(points)
                if next_offset is None:
                    return records
                offset = next_offset
        except Exception:
            logger.exception("Error scrolling points in %s", self.collection_name)
            raise

    async def scroll_all_ids_by_project(self, project_key: str) -> list[int]:
        """Retrieves all stored point IDs for a given project key using Qdrant scroll pagination."""
        try:
            if not await self._collection_exists():
                return []
            ids = []
            offset = None
            project_filter = models.Filter(
                must=[models.FieldCondition(key="project_key", match=models.MatchValue(value=project_key))]
            )
            while True:
                result, next_offset = await _retry_qdrant(
                    f"project scroll in {self.collection_name}",
                    lambda current_offset=offset: self.client.scroll(
                        collection_name=self.collection_name,
                        scroll_filter=project_filter,
                        limit=1000,
                        offset=current_offset,
                        with_payload=False,
                        with_vectors=False,
                    ),
                )
                ids.extend(p.id for p in result)
                if next_offset is None:
                    break
                offset = next_offset
            return ids
        except Exception:
            logger.exception("Error scrolling Vector DB")
            raise

    async def upsert_payload_record(self, record_id: str, payload: dict) -> None:
        """Store a metadata record by ID without vectors, since these writes must never call the embedding service."""
        try:
            await self.ensure_payload_collection()
            await _retry_qdrant(
                f"record write of {record_id} in {self.collection_name}",
                lambda: self.client.upsert(
                    collection_name=self.collection_name,
                    points=[models.PointStruct(id=_record_uuid(record_id), vector={}, payload=payload)],
                ),
            )
        except Exception:
            logger.exception("Error storing record %s in %s", record_id, self.collection_name)
            raise

    async def get_payload_record(self, record_id: str) -> dict | None:
        """Read one metadata record's payload, or None when it doesn't exist."""
        try:
            points = await _retry_qdrant(
                f"record read of {record_id} in {self.collection_name}",
                lambda: self.client.retrieve(
                    collection_name=self.collection_name,
                    ids=[_record_uuid(record_id)],
                ),
            )
            if points and points[0].payload:
                return points[0].payload
            return None
        except Exception:
            logger.exception("Error reading record %s from %s", record_id, self.collection_name)
            raise

    async def get_payload_record_if_exists(self, record_id: str) -> dict | None:
        """Read one record's payload without creating the collection.

        Returns None when the collection doesn't exist yet, so legacy-format reads
        never materialize a collection with the wrong (vector) schema (A7).
        """
        if not await self._collection_exists():
            return None
        return await self.get_payload_record(record_id)

    async def scroll_payload_records(self, filter_by: dict) -> list[dict]:
        """Scrolls every payload record whose fields match ``filter_by`` exactly.

        Used by the sync state to load one scope's fingerprints in one read.
        Never calls the embedding service: metadata records carry no vectors.
        """
        try:
            await self.ensure_payload_collection()
            must = [
                models.FieldCondition(key=key, match=models.MatchValue(value=value)) for key, value in filter_by.items()
            ]
            records: list[dict] = []
            offset = None
            while True:
                points, next_offset = await _retry_qdrant(
                    f"record scroll in {self.collection_name}",
                    lambda current_offset=offset: self.client.scroll(
                        collection_name=self.collection_name,
                        scroll_filter=models.Filter(must=must),
                        limit=1000,
                        offset=current_offset,
                        with_payload=True,
                        with_vectors=False,
                    ),
                )
                records.extend(point.payload for point in points if point.payload)
                if next_offset is None:
                    return records
                offset = next_offset
        except Exception:
            logger.exception("Error scrolling records matching %s in %s", filter_by, self.collection_name)
            raise

    async def delete_payload_record(self, record_id: str) -> None:
        """Delete one metadata record by ID."""
        try:
            await _retry_qdrant(
                f"record delete of {record_id} in {self.collection_name}",
                lambda: self.client.delete(
                    collection_name=self.collection_name,
                    points_selector=models.PointIdsList(points=[_record_uuid(record_id)]),
                ),
            )
        except Exception:
            logger.exception("Error deleting record %s from %s", record_id, self.collection_name)
            raise

    async def ensure_payload_collection(self) -> None:
        """Creates the metadata collection when missing. It holds no vectors, so no
        embedding call is needed; the vector params are minimal placeholders."""
        if self._ensured:
            return
        if await self._collection_exists():
            await self._ensure_payload_indexes()
            self._ensured = True
            return
        try:
            await self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={},
            )
            logger.info("Created vectorless metadata collection %s.", self.collection_name)
        except Exception as e:
            if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                logger.info("Collection %s already exists (race condition handled).", self.collection_name)
            else:
                raise e
        await self._ensure_payload_indexes()
        self._ensured = True

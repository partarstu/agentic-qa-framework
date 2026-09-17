# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
import time
import uuid

import httpx
from qdrant_client import AsyncQdrantClient, models

import config
from common import utils
from common.models import VectorizableBaseModel

logger = utils.get_logger("vector_db_service")

# Named vectors on every collection this service manages: dense + learned-sparse.
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"


# Payload fields indexed per collection kind after creation (WS7 plan table):
# matching is by collection name from configuration.
_DOCUMENTS_INDEXED_FIELDS = {
    "space_key": models.PayloadSchemaType.KEYWORD,
    "page_id": models.PayloadSchemaType.KEYWORD,
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
        self.client = AsyncQdrantClient(
            url=getattr(config.QdrantConfig, "URL", "http://localhost:6333"),
            port=None,
            api_key=getattr(config.QdrantConfig, "API_KEY", None),
            timeout=getattr(config.QdrantConfig, "TIMEOUT_SECONDS", 30),
        )
        self.embedding_service_url = getattr(config.QdrantConfig, "EMBEDDING_SERVICE_URL", None)
        if not self.embedding_service_url:
            logger.warning("EMBEDDING_SERVICE_URL is not configured. Vector operations requiring embeddings will fail.")
        timeout_seconds = getattr(config.QdrantConfig, "EMBEDDING_SERVICE_TIMEOUT_SECONDS", 120.0)
        self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))
        self._embedding_max_retries = getattr(config.QdrantConfig, "EMBEDDING_SERVICE_MAX_RETRIES", 6)
        self._embedding_retry_backoff_cap = getattr(
            config.QdrantConfig, "EMBEDDING_SERVICE_RETRY_BACKOFF_CAP_SECONDS", 32.0
        )
        # Collections whose writes must not go through the embedding service (locks, sync state,
        # fingerprints, model identity): records are stored without vectors. A shared instance
        # can be passed in so callers that also hold their own metadata service don't duplicate
        # clients against the same collection.
        self._metadata_db = metadata_db or (
            VectorDbService(metadata_collection_name) if metadata_collection_name and metadata_collection_name != collection_name else None
        )
        self._upsert_batch_size = int(getattr(config.QdrantConfig, "UPSERT_BATCH_SIZE", 64))
        # One ensure per collection per service instance is enough: index creation is
        # idempotent, and re-listing collections on every upsert/query wastes a round trip.
        self._ensured = False

    async def close(self):
        """Closes the shared HTTP client. Call this during application shutdown."""
        await self._http_client.aclose()
        if self._metadata_db is not None:
            await self._metadata_db.close()

    async def _embed_texts(self, texts: list[str], query: bool = False):
        """Embeds texts through the embedding service.

        Uses the document-text endpoint (no query instruction) unless ``query`` is set.
        Retries transient transport failures with backoff, honouring the configured caps.

        Returns:
            A tuple (embeddings, model): embeddings is a list of
            (dense vector, sparse indices, sparse values) tuples, one per input text;
            model is the identity of the model that produced them.
        """
        if not self.embedding_service_url:
            raise ValueError("EMBEDDING_SERVICE_URL is not configured.")

        endpoint = "/embed-query-text" if query else "/embed-document-text"
        max_retries = self._embedding_max_retries
        logger.info(f"Calling embedding service{endpoint} ({len(texts)} text(s))...")
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
                    (item["dense"], item["sparse"]["indices"], item["sparse"]["values"])
                    for item in body["embeddings"]
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
                logger.exception(f"HTTP error from embedding service: {e.response.status_code} - {e.response.text}")
                raise
            except Exception:
                logger.exception("Error calling embedding service")
                raise
        return None

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
        refuse to run with a different model. Payload indexes are (re-)ensured
        idempotently, so a collection created before its indexes existed still gets
        them on the next ensure.
        """
        if self._ensured:
            return
        if await self._collection_exists():
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
                sparse_vectors_config={
                    SPARSE_VECTOR_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
            )
            logger.info(f"Created collection {self.collection_name} with named dense({vector_size}) + sparse vectors.")
        except Exception as e:
            # Handle race condition where collection is created concurrently
            if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                logger.info(f"Collection {self.collection_name} already exists (race condition handled).")
            else:
                raise e

        await self._ensure_payload_indexes()

        if self._metadata_db is not None:
            await self._metadata_db._store_model_identity(self.collection_name, model)
        self._ensured = True

    def _indexed_fields(self) -> dict[str, models.PayloadSchemaType]:
        """The payload fields this collection should have indexes on (WS7), by collection name."""
        if self.collection_name == config.QdrantConfig.TICKETS_COLLECTION_NAME:
            return _JIRA_INDEXED_FIELDS
        if self.collection_name == config.QdrantConfig.METADATA_COLLECTION_NAME:
            return _METADATA_INDEXED_FIELDS
        if self.collection_name == config.DocumentRagConfig.DOCUMENTS_COLLECTION_NAME:
            return _DOCUMENTS_INDEXED_FIELDS
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
                logger.info(f"Created payload index on {field_name} in {self.collection_name}.")
            except Exception as e:
                if "already exists" in str(e).lower():
                    logger.info(f"Payload index on {field_name} in {self.collection_name} already exists.")
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
        await self.client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=self._model_identity_id(collection_name),
                    vector={},
                    payload={"kind": "model-identity", "collection": collection_name, "model": model},
                )
            ],
        )

    async def _get_model_identity(self, collection_name: str) -> str | None:
        """Read the recorded model for a collection, or None when it isn't recorded."""
        points = await self.client.retrieve(
            collection_name=self.collection_name,
            ids=[self._model_identity_id(collection_name)],
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
           branch (see the plan, WS7).
        4. Prefetches are fused with RRF.

        Args:
            query_text: The text to embed and search for.
            limit: Maximum number of fused results.
            score_threshold: Minimum similarity applied to the dense prefetch only.
            query_filter: Optional payload filter applied to every prefetch.
            with_payload: Payload selector; excludes heavy fields when needed.

        Returns:
            Fused scored points.
        """
        logger.info(f"Starting hybrid search in '{self.collection_name}' (limit {limit})...")
        try:
            if not await self._collection_exists():
                logger.warning(f"Collection {self.collection_name} doesn't exist yet in DB")
                return []
            embeddings, model = await self._embed_texts([query_text], query=True)
            dense, sparse_indices, sparse_values = embeddings[0]
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
            response = await self.client.query_points(
                collection_name=self.collection_name,
                prefetch=[dense_prefetch, sparse_prefetch],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=limit,
                with_payload=with_payload,
            )
            return response.points
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
            await self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    models.PointStruct(
                        id=point_id,
                        vector={
                            DENSE_VECTOR_NAME: dense,
                            SPARSE_VECTOR_NAME: models.SparseVector(indices=sparse_indices, values=sparse_values),
                        },
                        payload=payload,
                    )
                ],
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
                await self.client.upsert(collection_name=self.collection_name, points=points)
                logger.info(f"Upserted batch of {len(points)} point(s) to collection {self.collection_name}")
        except Exception:
            logger.exception("Error batch-upserting to Vector DB")
            raise

    async def retrieve(
        self,
        point_ids: list[int | str],
        with_payload: bool | dict | models.PayloadSelector | None = True,
    ) -> list[models.Record]:
        """Retrieve points by their IDs from the collection.

        Args:
            point_ids: List of point IDs to retrieve (64-bit unsigned integers or UUID strings).
            with_payload: Payload selector, so heavy fields can be excluded from reads.

        Returns:
            List of Record objects containing point data.

        Raises:
            Exception: If retrieval from Vector DB fails.
        """
        try:
            await self.ensure_collection()
            return await self.client.retrieve(
                collection_name=self.collection_name,
                ids=point_ids,
                with_payload=with_payload,
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
            await self.client.delete(
                collection_name=self.collection_name, points_selector=models.PointIdsList(points=point_ids)
            )
            logger.info(f"Deleted documents with IDs {point_ids} from collection {self.collection_name}")
        except Exception:
            logger.exception("Error deleting from Vector DB")
            raise

    async def has_points(self, scope_filter: models.Filter) -> bool:
        """Whether at least one point matches the filter; False when the collection doesn't exist."""
        if not await self._collection_exists():
            return False
        points, _ = await self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=scope_filter,
            limit=1,
            with_payload=False,
            with_vectors=False,
        )
        return bool(points)

    async def delete_by_filter(self, scope_filter: models.Filter):
        """Delete every point matching the filter (reconciliation of removed items)."""
        try:
            await self.client.delete(
                collection_name=self.collection_name, points_selector=models.FilterSelector(filter=scope_filter)
            )
            logger.info(f"Deleted points matching filter from collection {self.collection_name}")
        except Exception:
            logger.exception("Error deleting by filter from Vector DB")
            raise

    async def set_payload(self, payload: dict, point_ids: list[int | str] | None = None, scope_filter: models.Filter | None = None):
        """Payload-only update for metadata changes without re-embedding."""
        try:
            selector = (
                models.PointIdsList(points=point_ids)
                if point_ids is not None
                else models.FilterSelector(filter=scope_filter)
            )
            await self.client.set_payload(
                collection_name=self.collection_name,
                payload=payload,
                points=selector,
            )
            logger.info(f"Updated payload on {len(point_ids) if point_ids else 'filtered'} point(s) in {self.collection_name}")
        except Exception:
            logger.exception("Error updating payload in Vector DB")
            raise

    async def scroll_all_ids_by_project(self, project_key: str) -> list[int]:
        """Retrieves all stored point IDs for a given project key using Qdrant scroll pagination.

        Args:
            project_key: The project key to filter by.

        Returns:
            List of all numeric point IDs stored for the project.
        """
        try:
            if not await self._collection_exists():
                return []
            ids = []
            offset = None
            project_filter = models.Filter(
                must=[models.FieldCondition(key="project_key", match=models.MatchValue(value=project_key))]
            )
            while True:
                result, next_offset = await self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=project_filter,
                    limit=1000,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
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
        """Store a metadata record by ID without vectors or embedding (locks, sync state).

        Writing these records must never call the embedding service (WS7 plan), so the
        point carries no vectors at all.
        """
        try:
            await self.ensure_payload_collection()
            await self.client.upsert(
                collection_name=self.collection_name,
                points=[models.PointStruct(id=_record_uuid(record_id), vector={}, payload=payload)],
            )
        except Exception:
            logger.exception(f"Error storing record {record_id} in {self.collection_name}")
            raise

    async def get_payload_record(self, record_id: str) -> dict | None:
        """Read one metadata record's payload, or None when it doesn't exist."""
        try:
            points = await self.client.retrieve(
                collection_name=self.collection_name,
                ids=[_record_uuid(record_id)],
            )
            if points and points[0].payload:
                return points[0].payload
            return None
        except Exception:
            logger.exception(f"Error reading record {record_id} from {self.collection_name}")
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

        Used by the sync state (WS9) to load one scope's fingerprints in one read.
        Never calls the embedding service: metadata records carry no vectors.
        """
        try:
            await self.ensure_payload_collection()
            must = [models.FieldCondition(key=key, match=models.MatchValue(value=value)) for key, value in filter_by.items()]
            records: list[dict] = []
            offset = None
            while True:
                points, next_offset = await self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=models.Filter(must=must),
                    limit=1000,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                records.extend(point.payload for point in points if point.payload)
                if next_offset is None:
                    return records
                offset = next_offset
        except Exception:
            logger.exception(f"Error scrolling records matching {filter_by} in {self.collection_name}")
            raise

    async def delete_payload_record(self, record_id: str) -> None:
        """Delete one metadata record by ID."""
        try:
            await self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=[_record_uuid(record_id)]),
            )
        except Exception:
            logger.exception(f"Error deleting record {record_id} from {self.collection_name}")
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
            logger.info(f"Created vectorless metadata collection {self.collection_name}.")
        except Exception as e:
            if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                logger.info(f"Collection {self.collection_name} already exists (race condition handled).")
            else:
                raise e
        await self._ensure_payload_indexes()
        self._ensured = True

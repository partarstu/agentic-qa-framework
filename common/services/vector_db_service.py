# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import os
from typing import List

from qdrant_client import AsyncQdrantClient, models
import httpx

import config
from common import utils
from common.models import VectorizableBaseModel

from sentence_transformers import SentenceTransformer  # noqa: E402

logger = utils.get_logger("vector_db_service")


class VectorDbService:
    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self.client = AsyncQdrantClient(
            url=getattr(config.QdrantConfig, "URL", "http://localhost:6333"),
            api_key=getattr(config.QdrantConfig, "API_KEY", None),
        )
        self.model_name = getattr(config.QdrantConfig, "EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")
        self._embedding_model: SentenceTransformer | None = None
        self.embedding_service_url = getattr(config.QdrantConfig, "EMBEDDING_SERVICE_URL", None)

    @property
    def embedding_model(self) -> SentenceTransformer:
        """Lazily initialize and return the embedding model.

        If a pre-downloaded model exists at the configured path, it will be loaded
        from there. Otherwise, the model will be downloaded from the model name.
        """
        if self._embedding_model is None:
            model_path = getattr(config.QdrantConfig, "EMBEDDING_MODEL_PATH", None)

            if model_path and os.path.exists(model_path) and os.listdir(model_path):
                logger.info(f"Loading embedding model from local path: {model_path}")
                self._embedding_model = SentenceTransformer(model_path, trust_remote_code=True)
            else:
                logger.info(f"Downloading embedding model: {self.model_name}")
                self._embedding_model = SentenceTransformer(self.model_name, trust_remote_code=True)

        return self._embedding_model

    async def _get_embedding(self, text: str) -> List[float]:
        if self.embedding_service_url:
            timeout = httpx.Timeout(config.QdrantConfig.EMBEDDING_SERVICE_TIMEOUT_SECONDS)
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        f"{self.embedding_service_url}/embed",
                        json={"text": text}
                    )
                    response.raise_for_status()
                    return response.json()["embedding"]
            except httpx.TimeoutException:
                logger.exception(
                    f"Timeout calling embedding service at {self.embedding_service_url}"
                )
                raise
            except httpx.HTTPStatusError as e:
                logger.exception(
                    f"HTTP error from embedding service: {e.response.status_code} - {e.response.text}"
                )
                raise
            except Exception:
                logger.exception("Error calling embedding service")
                raise

        # Fallback to local model
        embedding = self.embedding_model.encode(text)
        return embedding.tolist()

    async def _ensure_collection(self):
        if not await self.client.collection_exists(self.collection_name):
            # We dynamically detect the vector size by embedding a dummy string
            dummy_vec = await self._get_embedding("test")
            vector_size = len(dummy_vec)

            try:
                await self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE)
                )
            except Exception as e:
                # Handle race condition where collection is created concurrently
                # Qdrant client might raise an error if collection already exists
                if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                    logger.info(f"Collection {self.collection_name} already exists (race condition handled).")
                else:
                    raise e

    async def search(
        self,
        query_text: str,
        limit: int = 5,
        score_threshold: float = 0.7,
        query_filter: models.Filter | None = None,
    ) -> List[models.ScoredPoint]:
        """Search for similar vectors in the collection.

        Args:
            query_text: The text to embed and search for.
            limit: Maximum number of results to return.
            score_threshold: Minimum similarity score threshold.
            query_filter: Optional Qdrant Filter object for payload-based filtering.

        Returns:
            List of scored points matching the query and filter conditions.
        """
        try:
            if not await self.client.collection_exists(self.collection_name):
                logger.warning(f"Collection {self.collection_name} doesn't exist yet in DB")
                return []
            embedding = await self._get_embedding(query_text)
            response = await self.client.query_points(
                collection_name=self.collection_name,
                query=embedding,
                limit=limit,
                score_threshold=score_threshold,
                query_filter=query_filter,
            )
            return response.points
        except Exception:
            logger.exception("Error querying Vector DB")
            return []

    async def upsert(self, data: VectorizableBaseModel):
        try:
            await self._ensure_collection()
            text = data.get_embedding_content()
            payload = data.model_dump()
            point_id = data.get_vector_id()

            embedding = await self._get_embedding(text)
            await self.client.upsert(
                collection_name=self.collection_name,
                points=[models.PointStruct(id=point_id, vector=embedding, payload=payload)]
            )
            logger.info(f"Upserted document with ID {point_id} to collection {self.collection_name}")
        except Exception:
            logger.exception("Error upserting to Vector DB")
            raise

    async def retrieve(self, point_ids: list[int | str]) -> list[models.Record]:
        """Retrieve points by their IDs from the collection.

        Args:
            point_ids: List of point IDs to retrieve (64-bit unsigned integers or UUID strings).

        Returns:
            List of Record objects containing point data.

        Raises:
            Exception: If retrieval from Vector DB fails.
        """
        try:
            await self._ensure_collection()
            return await self.client.retrieve(
                collection_name=self.collection_name,
                ids=point_ids,
            )
        except Exception:
            logger.exception("Error retrieving from Vector DB")
            raise

    async def delete(self, point_ids: list[int | str]):
        """Delete points by their IDs from the collection.

        Args:
            point_ids: List of point IDs to delete (64-bit unsigned integers or UUID strings).

        Raises:
            Exception: If deletion from Vector DB fails.
        """
        try:
            await self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(
                    points=point_ids
                )
            )
            logger.info(f"Deleted documents with IDs {point_ids} from collection {self.collection_name}")
        except Exception:
            logger.exception("Error deleting from Vector DB")
            raise

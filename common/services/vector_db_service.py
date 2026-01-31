# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0


import asyncio

import httpx
from qdrant_client import AsyncQdrantClient, models

import config
from common import utils
from common.models import VectorizableBaseModel

logger = utils.get_logger("vector_db_service")


class VectorDbService:
    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self.client = AsyncQdrantClient(
            url=getattr(config.QdrantConfig, "URL", "http://localhost"),
            port=getattr(config.QdrantConfig, "PORT", 6333),
            grpc_port=getattr(config.QdrantConfig, "GRPC_PORT", 6334),
            prefer_grpc=True,
            api_key=getattr(config.QdrantConfig, "API_KEY", None),
            timeout=getattr(config.QdrantConfig, "TIMEOUT_SECONDS", 30.0),
        )
        self.embedding_service_url = getattr(config.QdrantConfig, "EMBEDDING_SERVICE_URL", None)
        if not self.embedding_service_url:
            logger.warning("EMBEDDING_SERVICE_URL is not configured. Vector operations requiring embeddings will fail.")

    async def _get_embedding(self, text: str) -> list[float]|None:
        if not self.embedding_service_url:
            raise ValueError("EMBEDDING_SERVICE_URL is not configured.")

        timeout_seconds = getattr(config.QdrantConfig, "EMBEDDING_SERVICE_TIMEOUT_SECONDS", 120.0)
        timeout = httpx.Timeout(timeout_seconds)
        max_retries = 3

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(f"{self.embedding_service_url}/embed", json={"text": text})
                    response.raise_for_status()
                    return response.json()["embedding"]
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt == max_retries - 1:
                    logger.exception(f"Failed to call embedding service at {self.embedding_service_url} after {max_retries} attempts.")
                    raise
                wait_time = 2 ** attempt
                logger.warning(f"Attempt {attempt + 1}/{max_retries} failed calling embedding service: {e}. Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
            except httpx.HTTPStatusError as e:
                logger.exception(f"HTTP error from embedding service: {e.response.status_code} - {e.response.text}")
                raise
            except Exception:
                logger.exception("Error calling embedding service")
                raise
        return None

    async def _ensure_collection(self):
        if not await self.client.collection_exists(self.collection_name):
            # Dynamically detect the vector size by embedding a dummy string
            dummy_vec = await self._get_embedding("test")
            vector_size = len(dummy_vec)

            try:
                await self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE)
                )
            except Exception as e:
                # Handle race condition where collection is created concurrently
                if "already exists" in str(e).lower() or "conflict" in str(e).lower():
                    logger.info(f"Collection {self.collection_name} already exists (race condition handled).")
                else:
                    raise e

    async def search(self, query_text: str, limit: int = 5, score_threshold: float = 0.7, query_filter: models.Filter | None = None,
                     ) -> list[models.ScoredPoint]:
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
            raise

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
            return await self.client.retrieve(collection_name=self.collection_name, ids=point_ids, )
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
            await self.client.delete(collection_name=self.collection_name, points_selector=models.PointIdsList(points=point_ids))
            logger.info(f"Deleted documents with IDs {point_ids} from collection {self.collection_name}")
        except Exception:
            logger.exception("Error deleting from Vector DB")
            raise

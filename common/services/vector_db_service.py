# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import uuid
from typing import List, Dict, Any, Union

from qdrant_client import AsyncQdrantClient, models
from sentence_transformers import SentenceTransformer
from pydantic import BaseModel

import config
from common import utils

logger = utils.get_logger("vector_db_service")


class VectorDbService:
    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self.client = AsyncQdrantClient(
            url=getattr(config.QdrantConfig, "URL", "http://localhost:6333"),
            api_key=getattr(config.QdrantConfig, "API_KEY", None),
        )
        self.model_name = getattr(config.QdrantConfig, "EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")
        
        logger.info(f"Initializing VectorDbService with model: {self.model_name}")
        self.embedding_model = SentenceTransformer(self.model_name)

    def _get_embedding(self, text: str) -> List[float]:
        embedding = self.embedding_model.encode(text)
        return embedding.tolist()

    async def _ensure_collection(self):
        if not await self.client.collection_exists(self.collection_name):
            # We dynamically detect the vector size by embedding a dummy string
            dummy_vec = self._get_embedding("test")
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

    async def search(self, query_text: str, limit: int = 5, score_threshold: float = 0.7) -> List[models.ScoredPoint]:
        try:
            embedding = self._get_embedding(query_text)
            response = await self.client.query_points(
                collection_name=self.collection_name,
                query=embedding,
                limit=limit,
                score_threshold=score_threshold
            )
            return response.points
        except Exception as e:
            logger.error(f"Error querying Vector DB: {e}")
            return []

    async def upsert(self, data: Union[str, BaseModel], metadata: Dict[str, Any] = None, point_id: str = None):
        try:
            await self._ensure_collection()
            
            if isinstance(data, str):
                text = data
                payload = {"content": text}
            else:
                text = str(data)
                payload = data.model_dump()
            
            if metadata:
                payload.update(metadata)
                
            embedding = self._get_embedding(text)
            
            if not point_id:
                # Try to find an ID in the model if available
                if not isinstance(data, str):
                     if hasattr(data, "id"):
                        point_id = str(data.id)
                     elif hasattr(data, "key"):
                        point_id = str(data.key)
                
                if not point_id:
                    point_id = str(uuid.uuid4())
            
            await self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    models.PointStruct(
                        id=point_id,
                        vector=embedding,
                        payload=payload
                    )
                ]
            )
            logger.info(f"Upserted document with ID {point_id} to collection {self.collection_name}")
        except Exception as e:
            logger.error(f"Error upserting to Vector DB: {e}")

    async def delete(self, point_ids: List[str]):
        try:
            await self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(
                    points=point_ids
                )
            )
            logger.info(f"Deleted documents with IDs {point_ids} from collection {self.collection_name}")
        except Exception as e:
            logger.error(f"Error deleting from Vector DB: {e}")

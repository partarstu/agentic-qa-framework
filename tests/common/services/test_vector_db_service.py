# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from qdrant_client import models

from common.models import VectorizableBaseModel
from common.services.vector_db_service import VectorDbService


class DummyModel(VectorizableBaseModel):
    id: str
    content: str

    def get_vector_id(self) -> str:
        return self.id

    def get_embedding_content(self) -> str:
        return self.content

@pytest.fixture
def mock_qdrant_client():
    with patch("common.services.vector_db_service.AsyncQdrantClient") as mock:
        client_instance = AsyncMock()
        mock.return_value = client_instance
        yield client_instance

@pytest.fixture
def mock_httpx_client():
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        # Mock the post response
        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
        mock_response.raise_for_status.return_value = None
        mock_client.post.return_value = mock_response

        yield mock_client

@pytest.fixture
def vector_db_service(mock_qdrant_client, mock_httpx_client):
    with patch("common.services.vector_db_service.config.QdrantConfig") as mock_config:
        mock_config.URL = "http://localhost"
        mock_config.PORT = 6333
        mock_config.GRPC_PORT = 6334
        mock_config.API_KEY = None
        mock_config.TIMEOUT_SECONDS = 30.0
        # This is now required
        mock_config.EMBEDDING_SERVICE_URL = "http://embedding-service:8080"
        mock_config.EMBEDDING_SERVICE_TIMEOUT_SECONDS = 60.0

        return VectorDbService("test_collection")

def test_init(mock_qdrant_client):
    with patch("common.services.vector_db_service.config.QdrantConfig") as mock_config:
        mock_config.URL = "http://localhost"
        mock_config.PORT = 6333
        mock_config.GRPC_PORT = 6334
        mock_config.API_KEY = "test_key"
        mock_config.TIMEOUT_SECONDS = 30.0
        mock_config.EMBEDDING_SERVICE_URL = "http://embedding-service:8080"

        VectorDbService("test_collection")

        # Verify AsyncQdrantClient was initialized with expected parameters including gRPC
        from common.services.vector_db_service import AsyncQdrantClient
        AsyncQdrantClient.assert_called_with(
            url="http://localhost",
            port=6333,
            grpc_port=6334,
            prefer_grpc=True,
            api_key="test_key",
            timeout=30.0
        )

def test_init_missing_service_url(mock_qdrant_client):
    with patch("common.services.vector_db_service.config.QdrantConfig") as mock_config:
        mock_config.URL = "http://localhost"
        mock_config.PORT = 6333
        mock_config.GRPC_PORT = 6334
        mock_config.API_KEY = "test_key"
        mock_config.TIMEOUT_SECONDS = 30.0
        mock_config.EMBEDDING_SERVICE_URL = None

        # It logs a warning but doesn't crash on init
        VectorDbService("test_collection")

@pytest.mark.asyncio
async def test_ensure_collection_exists(vector_db_service, mock_qdrant_client):
    mock_qdrant_client.collection_exists.return_value = True
    await vector_db_service._ensure_collection()
    mock_qdrant_client.create_collection.assert_not_called()

@pytest.mark.asyncio
async def test_ensure_collection_creates(vector_db_service, mock_qdrant_client, mock_httpx_client):
    mock_qdrant_client.collection_exists.return_value = False
    await vector_db_service._ensure_collection()
    mock_qdrant_client.create_collection.assert_called_once()
    # Ensure it called the embedding service to check vector size
    mock_httpx_client.post.assert_called()

@pytest.mark.asyncio
async def test_ensure_collection_race_condition(vector_db_service, mock_qdrant_client):
    mock_qdrant_client.collection_exists.return_value = False
    mock_qdrant_client.create_collection.side_effect = Exception("Collection `test_collection` already exists!")

    # Should not raise exception
    await vector_db_service._ensure_collection()

    mock_qdrant_client.create_collection.assert_called_once()

@pytest.mark.asyncio
async def test_search(vector_db_service, mock_qdrant_client, mock_httpx_client):
    mock_response = MagicMock()
    mock_response.points = [models.ScoredPoint(id="1", version=1, score=0.9, payload={}, vector=None)]
    mock_qdrant_client.query_points.return_value = mock_response

    results = await vector_db_service.search("query")
    assert len(results) == 1
    mock_qdrant_client.query_points.assert_called_once()
    # Check if embedding service was called
    mock_httpx_client.post.assert_called()

@pytest.mark.asyncio
async def test_upsert(vector_db_service, mock_qdrant_client, mock_httpx_client):
    mock_qdrant_client.collection_exists.return_value = True
    data = DummyModel(id="123", content="text")
    await vector_db_service.upsert(data)
    mock_qdrant_client.upsert.assert_called_once()
    # Check if embedding service was called
    mock_httpx_client.post.assert_called()

@pytest.mark.asyncio
async def test_delete(vector_db_service, mock_qdrant_client):
    await vector_db_service.delete(["1", "2"])
    mock_qdrant_client.delete.assert_called_once()

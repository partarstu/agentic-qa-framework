# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

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
        mock_client_cls.return_value = mock_client

        def _respond_to_post(url, json=None, headers=None):
            mock_response = MagicMock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {
                "embeddings": [
                    {"dense": [0.1, 0.2, 0.3], "sparse": {"indices": [1, 2], "values": [0.5, 0.6]}}
                    for _ in (json or {}).get("texts", [])
                ]
            }
            return mock_response

        mock_client.post = AsyncMock(side_effect=_respond_to_post)

        yield mock_client


@pytest.fixture
def vector_db_service(mock_qdrant_client, mock_httpx_client):
    with patch("common.services.vector_db_service.config.QdrantConfig") as mock_config:
        mock_config.URL = "http://localhost"
        mock_config.PORT = 6333
        mock_config.API_KEY = None
        mock_config.TIMEOUT_SECONDS = 30.0
        mock_config.EMBEDDING_SERVICE_URL = "http://embedding-service:8080"
        mock_config.EMBEDDING_SERVICE_TIMEOUT_SECONDS = 60.0

        return VectorDbService("test_collection")


def test_init(mock_qdrant_client):
    with patch("common.services.vector_db_service.config.QdrantConfig") as mock_config:
        mock_config.URL = "http://localhost"
        mock_config.PORT = 6333
        mock_config.API_KEY = "test_key"
        mock_config.TIMEOUT_SECONDS = 30.0
        mock_config.EMBEDDING_SERVICE_URL = "http://embedding-service:8080"

        VectorDbService("test_collection")

        from common.services.vector_db_service import AsyncQdrantClient

        AsyncQdrantClient.assert_called_with(url="http://localhost", port=6333, api_key="test_key", timeout=30.0)


def test_init_missing_service_url(mock_qdrant_client):
    with patch("common.services.vector_db_service.config.QdrantConfig") as mock_config:
        mock_config.URL = "http://localhost"
        mock_config.PORT = 6333
        mock_config.API_KEY = "test_key"
        mock_config.TIMEOUT_SECONDS = 30.0
        mock_config.EMBEDDING_SERVICE_URL = None

        # It logs a warning but doesn't crash on init
        VectorDbService("test_collection")


def _mock_collections_exist(mock_qdrant_client, collection_name: str, exists: bool):
    mock_collection = MagicMock()
    mock_collection.name = collection_name
    mock_result = MagicMock()
    mock_result.collections = [mock_collection] if exists else []
    mock_qdrant_client.get_collections.return_value = mock_result


@pytest.mark.asyncio
async def test_ensure_collection_exists(vector_db_service, mock_qdrant_client):
    _mock_collections_exist(mock_qdrant_client, "test_collection", exists=True)
    await vector_db_service.ensure_collection()
    mock_qdrant_client.create_collection.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_collection_creates(vector_db_service, mock_qdrant_client, mock_httpx_client):
    _mock_collections_exist(mock_qdrant_client, "test_collection", exists=False)
    await vector_db_service.ensure_collection()
    mock_qdrant_client.create_collection.assert_called_once()
    mock_httpx_client.post.assert_called()


@pytest.mark.asyncio
async def test_ensure_collection_race_condition(vector_db_service, mock_qdrant_client):
    _mock_collections_exist(mock_qdrant_client, "test_collection", exists=False)
    mock_qdrant_client.create_collection.side_effect = Exception("Collection `test_collection` already exists!")

    # Should not raise exception
    await vector_db_service.ensure_collection()

    mock_qdrant_client.create_collection.assert_called_once()


@pytest.mark.asyncio
async def test_search(vector_db_service, mock_qdrant_client, mock_httpx_client):
    _mock_collections_exist(mock_qdrant_client, "test_collection", exists=True)
    mock_response = MagicMock()
    mock_response.points = [models.ScoredPoint(id="1", version=1, score=0.9, payload={}, vector=None)]
    mock_qdrant_client.query_points.return_value = mock_response

    results = await vector_db_service.search("query")
    assert len(results) == 1
    mock_qdrant_client.query_points.assert_called_once()
    mock_httpx_client.post.assert_called()


@pytest.mark.asyncio
async def test_upsert(vector_db_service, mock_qdrant_client, mock_httpx_client):
    _mock_collections_exist(mock_qdrant_client, "test_collection", exists=True)
    data = DummyModel(id="123", content="text")
    await vector_db_service.upsert(data)
    mock_qdrant_client.upsert.assert_called_once()
    mock_httpx_client.post.assert_called()


@pytest.mark.asyncio
async def test_delete(vector_db_service, mock_qdrant_client):
    await vector_db_service.delete(["1", "2"])
    mock_qdrant_client.delete.assert_called_once()


@pytest.mark.asyncio
async def test_embed_texts_returns_dense_and_sparse_per_text(vector_db_service, mock_httpx_client):
    embeddings = await vector_db_service._embed_texts(["one", "two"])
    assert len(embeddings) == 2
    assert embeddings[0] == ([0.1, 0.2, 0.3], [1, 2], [0.5, 0.6])
    called_url = mock_httpx_client.post.call_args.args[0]
    assert called_url.endswith("/embed-document-text")
    assert mock_httpx_client.post.call_args.kwargs["json"] == {"texts": ["one", "two"]}


@pytest.mark.asyncio
async def test_embed_texts_query_uses_query_endpoint(vector_db_service, mock_httpx_client):
    await vector_db_service._embed_texts(["query"], query=True)
    called_url = mock_httpx_client.post.call_args.args[0]
    assert called_url.endswith("/embed-query-text")


@pytest.mark.asyncio
async def test_get_embedding_returns_dense_only(vector_db_service, mock_httpx_client):
    dense = await vector_db_service._get_embedding("text")
    assert dense == [0.1, 0.2, 0.3]

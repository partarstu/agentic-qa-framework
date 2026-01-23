# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from common.services.vector_db_service import VectorDbService
from common.models import VectorizableBaseModel
from qdrant_client import models

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
def mock_sentence_transformer():
    with patch("common.services.vector_db_service.SentenceTransformer") as mock:
        model_instance = MagicMock()
        # Mock encode to return an object with tolist method
        mock_embedding = MagicMock()
        mock_embedding.tolist.return_value = [0.1, 0.2, 0.3]
        # Also make it behave like a list for len() if needed, 
        # but _get_embedding only calls tolist()
        # However, _ensure_collection calls len(dummy_vec) AFTER tolist()
        
        model_instance.encode.return_value = mock_embedding
        mock.return_value = model_instance
        yield model_instance

@pytest.fixture
def vector_db_service(mock_qdrant_client, mock_sentence_transformer):
    with patch("common.services.vector_db_service.config.QdrantConfig") as mock_config:
        mock_config.URL = "http://localhost"
        mock_config.PORT = 6333
        mock_config.GRPC_PORT = 6334
        mock_config.API_KEY = None
        mock_config.TIMEOUT_SECONDS = 30.0
        mock_config.EMBEDDING_MODEL = "test_model"
        mock_config.EMBEDDING_SERVICE_URL = None
        mock_config.EMBEDDING_MODEL_PATH = None
        
        return VectorDbService("test_collection")

def test_init(mock_qdrant_client):
    with patch("common.services.vector_db_service.config.QdrantConfig") as mock_config:
        mock_config.URL = "http://localhost"
        mock_config.PORT = 6333
        mock_config.GRPC_PORT = 6334
        mock_config.API_KEY = "test_key"
        mock_config.TIMEOUT_SECONDS = 30.0
        mock_config.EMBEDDING_MODEL = "test_model"
        mock_config.EMBEDDING_SERVICE_URL = None
        
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

@pytest.mark.asyncio
async def test_ensure_collection_exists(vector_db_service, mock_qdrant_client):
    mock_qdrant_client.collection_exists.return_value = True
    await vector_db_service._ensure_collection()
    mock_qdrant_client.create_collection.assert_not_called()

@pytest.mark.asyncio
async def test_ensure_collection_creates(vector_db_service, mock_qdrant_client):
    mock_qdrant_client.collection_exists.return_value = False
    await vector_db_service._ensure_collection()
    mock_qdrant_client.create_collection.assert_called_once()

@pytest.mark.asyncio
async def test_ensure_collection_race_condition(vector_db_service, mock_qdrant_client):
    mock_qdrant_client.collection_exists.return_value = False
    mock_qdrant_client.create_collection.side_effect = Exception("Collection `test_collection` already exists!")
    
    # Should not raise exception
    await vector_db_service._ensure_collection()
    
    mock_qdrant_client.create_collection.assert_called_once()

@pytest.mark.asyncio
async def test_search(vector_db_service, mock_qdrant_client):
    mock_response = MagicMock()
    mock_response.points = [models.ScoredPoint(id="1", version=1, score=0.9, payload={}, vector=None)]
    mock_qdrant_client.query_points.return_value = mock_response
    
    results = await vector_db_service.search("query")
    assert len(results) == 1
    mock_qdrant_client.query_points.assert_called_once()

@pytest.mark.asyncio
async def test_upsert(vector_db_service, mock_qdrant_client):
    mock_qdrant_client.collection_exists.return_value = True
    data = DummyModel(id="123", content="text")
    await vector_db_service.upsert(data)
    mock_qdrant_client.upsert.assert_called_once()

@pytest.mark.asyncio
async def test_delete(vector_db_service, mock_qdrant_client):
    await vector_db_service.delete(["1", "2"])
    mock_qdrant_client.delete.assert_called_once()

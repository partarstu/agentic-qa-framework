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
                "model": "test-model",
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
        mock_config.API_KEY = None
        mock_config.TIMEOUT_SECONDS = 30.0
        mock_config.EMBEDDING_SERVICE_URL = "http://embedding-service:8080"
        mock_config.EMBEDDING_SERVICE_TIMEOUT_SECONDS = 60.0
        mock_config.UPSERT_BATCH_SIZE = 2

        return VectorDbService("test_collection")


def test_init(mock_qdrant_client):
    with patch("common.services.vector_db_service.config.QdrantConfig") as mock_config:
        mock_config.URL = "http://localhost"
        mock_config.API_KEY = "test_key"
        mock_config.TIMEOUT_SECONDS = 30.0
        mock_config.EMBEDDING_SERVICE_URL = "http://embedding-service:8080"

        VectorDbService("test_collection")

        from common.services.vector_db_service import AsyncQdrantClient

        # port=None keeps the client from appending its own default port to QDRANT_URL (WS7).
        AsyncQdrantClient.assert_called_with(url="http://localhost", port=None, api_key="test_key", timeout=30.0)


def test_init_missing_service_url(mock_qdrant_client):
    with patch("common.services.vector_db_service.config.QdrantConfig") as mock_config:
        mock_config.URL = "http://localhost"
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
    embeddings, model = await vector_db_service._embed_texts(["one", "two"])
    assert len(embeddings) == 2
    assert embeddings[0] == ([0.1, 0.2, 0.3], [1, 2], [0.5, 0.6])
    assert model == "test-model"
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


@pytest.mark.asyncio
async def test_hybrid_search_composes_prefetches_with_rrf(vector_db_service, mock_qdrant_client, mock_httpx_client):
    _mock_collections_exist(mock_qdrant_client, "test_collection", exists=True)
    mock_response = MagicMock()
    mock_response.points = [models.ScoredPoint(id="1", version=1, score=1.0, payload={}, vector=None)]
    mock_qdrant_client.query_points.return_value = mock_response

    query_filter = models.Filter(must=[models.FieldCondition(key="issue_type", match=models.MatchValue(value="Bug"))])
    results = await vector_db_service.hybrid_search("incident text", limit=7, score_threshold=0.7, query_filter=query_filter)

    assert len(results) == 1
    call = mock_qdrant_client.query_points.call_args
    dense_prefetch, sparse_prefetch = call.kwargs["prefetch"]
    # One prefetch per named vector, each covering the final limit...
    assert dense_prefetch.using == "dense"
    assert dense_prefetch.limit == 7
    assert sparse_prefetch.using == "sparse"
    assert sparse_prefetch.limit == 7
    # ...with the SAME filter, but the threshold only on the dense branch.
    assert dense_prefetch.filter == query_filter
    assert sparse_prefetch.filter == query_filter
    assert dense_prefetch.score_threshold == 0.7
    assert sparse_prefetch.score_threshold is None
    # Fused with RRF at the outer query.
    assert call.kwargs["query"].fusion == models.Fusion.RRF
    assert call.kwargs["limit"] == 7


@pytest.mark.asyncio
async def test_hybrid_search_without_threshold_keeps_prefetch_unfiltered(vector_db_service, mock_qdrant_client, mock_httpx_client):
    """The sparse-no-match edge case (qdrant#4937) is mitigated by the dense-only threshold:
    without a threshold the sparse branch may surface unrelated points, which the caller opts into."""
    _mock_collections_exist(mock_qdrant_client, "test_collection", exists=True)
    mock_qdrant_client.query_points.return_value = MagicMock(points=[])

    await vector_db_service.hybrid_search("incident text", limit=5)

    dense_prefetch, _ = mock_qdrant_client.query_points.call_args.kwargs["prefetch"]
    assert dense_prefetch.score_threshold is None


@pytest.mark.asyncio
async def test_hybrid_search_missing_collection_returns_empty(vector_db_service, mock_qdrant_client):
    _mock_collections_exist(mock_qdrant_client, "test_collection", exists=False)
    results = await vector_db_service.hybrid_search("incident text")
    assert results == []
    mock_qdrant_client.query_points.assert_not_called()


@pytest.fixture
def service_with_metadata_db(mock_qdrant_client, mock_httpx_client):
    with patch("common.services.vector_db_service.config.QdrantConfig") as mock_config:
        mock_config.URL = "http://localhost"
        mock_config.API_KEY = None
        mock_config.TIMEOUT_SECONDS = 30.0
        mock_config.EMBEDDING_SERVICE_URL = "http://embedding-service:8080"
        mock_config.EMBEDDING_SERVICE_TIMEOUT_SECONDS = 60.0
        mock_config.UPSERT_BATCH_SIZE = 2

        issues_db = VectorDbService("issues")
        metadata_db = VectorDbService("metadata")
        issues_db._metadata_db = metadata_db
        # No stored model identity by default; individual tests record one.
        metadata_db.client.retrieve.return_value = []
        return issues_db, metadata_db


@pytest.mark.asyncio
async def test_model_identity_stored_on_first_write(service_with_metadata_db, mock_qdrant_client):
    issues_db, metadata_db = service_with_metadata_db

    await issues_db._verify_model_identity("test-model")

    metadata_db.client.upsert.assert_called_once()
    point = metadata_db.client.upsert.call_args.kwargs["points"][0]
    assert point.payload["kind"] == "model-identity"
    assert point.payload["collection"] == "issues"
    assert point.payload["model"] == "test-model"


@pytest.mark.asyncio
async def test_model_identity_mismatch_refuses(service_with_metadata_db, mock_qdrant_client):
    issues_db, metadata_db = service_with_metadata_db
    stored = MagicMock()
    stored.payload = {"model": "old-model"}
    metadata_db.client.retrieve.return_value = [stored]

    with pytest.raises(RuntimeError, match=r"old-model.*test-model"):
        await issues_db._verify_model_identity("test-model")


@pytest.mark.asyncio
async def test_model_identity_matching_model_passes(service_with_metadata_db, mock_qdrant_client):
    issues_db, metadata_db = service_with_metadata_db
    stored = MagicMock()
    stored.payload = {"model": "test-model"}
    metadata_db.client.retrieve.return_value = [stored]

    await issues_db._verify_model_identity("test-model")

    metadata_db.client.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_batch_respects_batch_size(vector_db_service, mock_qdrant_client, mock_httpx_client):
    _mock_collections_exist(mock_qdrant_client, "test_collection", exists=True)
    items = [DummyModel(id=str(i), content=f"text {i}") for i in range(5)]

    await vector_db_service.upsert_batch(items, ensure=False)

    # UPSERT_BATCH_SIZE=2 in the fixture: 5 items -> 3 upsert calls (2 + 2 + 1).
    assert mock_qdrant_client.upsert.call_count == 3
    first_call_points = mock_qdrant_client.upsert.call_args_list[0].kwargs["points"]
    assert len(first_call_points) == 2
    point = first_call_points[0]
    assert set(point.vector.keys()) == {"dense", "sparse"}
    assert point.vector["dense"] == [0.1, 0.2, 0.3]
    assert point.vector["sparse"].indices == [1, 2]


@pytest.mark.asyncio
async def test_delete_by_filter_uses_filter_selector(vector_db_service, mock_qdrant_client):
    scope_filter = models.Filter(must=[models.FieldCondition(key="space_key", match=models.MatchValue(value="DEV"))])

    await vector_db_service.delete_by_filter(scope_filter)

    selector = mock_qdrant_client.delete.call_args.kwargs["points_selector"]
    assert selector.filter == scope_filter


@pytest.mark.asyncio
async def test_set_payload_by_ids_and_by_filter(vector_db_service, mock_qdrant_client):
    await vector_db_service.set_payload({"title": "renamed"}, point_ids=[1, 2])
    first_selector = mock_qdrant_client.set_payload.call_args.kwargs["points"]
    assert first_selector.points == [1, 2]

    scope_filter = models.Filter(must=[models.FieldCondition(key="space_key", match=models.MatchValue(value="DEV"))])
    await vector_db_service.set_payload({"title": "renamed"}, scope_filter=scope_filter)
    second_selector = mock_qdrant_client.set_payload.call_args.kwargs["points"]
    assert second_selector.filter == scope_filter


@pytest.mark.asyncio
async def test_retrieve_accepts_payload_selector(vector_db_service, mock_qdrant_client):
    selector = models.PayloadSelectorExclude(exclude=["page_image"])

    await vector_db_service.retrieve(["1"], with_payload=selector)

    assert mock_qdrant_client.retrieve.call_args.kwargs["with_payload"] == selector

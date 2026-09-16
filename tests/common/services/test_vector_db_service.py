# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import base64
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from qdrant_client import models

from common.models import DocumentPagePart, VectorizableBaseModel
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
            if url.endswith("/embed-page-image"):
                payload = {"model": "visual-model", "vectors": [[0.3, 0.4] for _ in (json or {}).get("images", [])]}
            elif url.endswith("/embed-visual-query-text"):
                payload = {"model": "visual-model", "vectors": [[0.5, 0.6] for _ in (json or {}).get("texts", [])]}
            else:
                payload = {
                    "model": "test-model",
                    "embeddings": [
                        {"dense": [0.1, 0.2, 0.3], "sparse": {"indices": [1, 2], "values": [0.5, 0.6]}}
                        for _ in (json or {}).get("texts", [])
                    ],
                }
            mock_response.json.return_value = payload
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


# --- Visual mode (opt-in, documents collection) -------------------------------------------


DOCUMENTS_COLLECTION = "confluence_documents"


def _document_part(**overrides) -> DocumentPagePart:
    fields = {
        "space_key": "DOC",
        "page_id": "111",
        "page_title": "Home",
        "attachment_id": "att-1",
        "attachment_name": "guide.pdf",
        "content_kind": "attachment",
        "document_name": "guide.pdf",
        "breadcrumb": "Home > guide.pdf > page 1 of 1",
        "text": "Home > guide.pdf > page 1 of 1\n\ncontent",
        "page_number": 1,
        "page_count": 1,
        "part_index": 0,
    }
    fields.update(overrides)
    return DocumentPagePart(**fields)


def test_default_visual_image_is_none():
    assert DummyModel(id="1", content="text").get_visual_image() is None


@contextlib.contextmanager
def documents_service(visual_enabled: bool):
    """A documents-collection service with mocked boundaries and the visual flag set."""
    with (
        patch("common.services.vector_db_service.config.QdrantConfig") as mock_config,
        patch("config.DocumentRagConfig.VISUAL_ENABLED", visual_enabled),
    ):
        mock_config.URL = "http://localhost"
        mock_config.API_KEY = None
        mock_config.TIMEOUT_SECONDS = 30.0
        mock_config.EMBEDDING_SERVICE_URL = "http://embedding-service:8080"
        mock_config.EMBEDDING_SERVICE_TIMEOUT_SECONDS = 60.0
        mock_config.UPSERT_BATCH_SIZE = 2
        service = VectorDbService(DOCUMENTS_COLLECTION)
        metadata_db = VectorDbService("metadata")
        service._metadata_db = metadata_db
        metadata_db.client.retrieve.return_value = []
        yield service, metadata_db


def _visual_posts(mock_httpx_client) -> list:
    return [c for c in mock_httpx_client.post.call_args_list if "visual" in c.args[0]]


@pytest.mark.asyncio
async def test_ensure_collection_visual_adds_visual_vector_and_identity(mock_qdrant_client, mock_httpx_client):
    _mock_collections_exist(mock_qdrant_client, DOCUMENTS_COLLECTION, exists=False)
    with documents_service(visual_enabled=True) as (service, metadata_db):
        await service.ensure_collection()

    vectors_config = mock_qdrant_client.create_collection.call_args.kwargs["vectors_config"]
    # Text vector size detected from the text probe (3), visual size from the visual probe (2).
    assert vectors_config["dense"].size == 3
    assert vectors_config["visual"].size == 2
    identity_points = [call.kwargs["points"][0] for call in metadata_db.client.upsert.call_args_list]
    assert {point.id for point in identity_points} == {
        "model-identity-confluence_documents",
        "model-identity-visual-confluence_documents",
    }
    visual_identity = next(p for p in identity_points if p.id == "model-identity-visual-confluence_documents")
    assert visual_identity.payload["model"] == "visual-model"


@pytest.mark.asyncio
async def test_ensure_collection_without_visual_stays_dense_and_sparse(mock_qdrant_client, mock_httpx_client):
    _mock_collections_exist(mock_qdrant_client, DOCUMENTS_COLLECTION, exists=False)
    with documents_service(visual_enabled=False) as (service, metadata_db):
        await service.ensure_collection()

    vectors_config = mock_qdrant_client.create_collection.call_args.kwargs["vectors_config"]
    assert set(vectors_config) == {"dense"}
    assert _visual_posts(mock_httpx_client) == []
    assert metadata_db.client.upsert.call_count == 1  # text identity only


@pytest.mark.asyncio
async def test_hybrid_search_visual_adds_third_prefetch(mock_qdrant_client, mock_httpx_client):
    _mock_collections_exist(mock_qdrant_client, DOCUMENTS_COLLECTION, exists=True)
    mock_qdrant_client.query_points.return_value = MagicMock(points=[])
    with documents_service(visual_enabled=True) as (service, metadata_db):
        await service.hybrid_search("query", limit=6, score_threshold=0.7)

    prefetches = mock_qdrant_client.query_points.call_args.kwargs["prefetch"]
    assert [prefetch.using for prefetch in prefetches] == ["dense", "sparse", "visual"]
    # The threshold still applies to the dense branch only.
    assert prefetches[0].score_threshold == 0.7
    assert prefetches[1].score_threshold is None
    assert prefetches[2].score_threshold is None
    assert prefetches[2].limit == 6
    assert len(_visual_posts(mock_httpx_client)) == 1
    # The visual model identity is checked against its own record.
    retrieved_ids = [call.kwargs["ids"] for call in metadata_db.client.retrieve.call_args_list]
    assert ["model-identity-visual-confluence_documents"] in retrieved_ids


@pytest.mark.asyncio
async def test_hybrid_search_without_visual_matches_text_only_behaviour(mock_qdrant_client, mock_httpx_client):
    _mock_collections_exist(mock_qdrant_client, DOCUMENTS_COLLECTION, exists=True)
    mock_qdrant_client.query_points.return_value = MagicMock(points=[])
    with documents_service(visual_enabled=False) as (service, metadata_db):
        await service.hybrid_search("query", limit=6, score_threshold=0.7)

    prefetches = mock_qdrant_client.query_points.call_args.kwargs["prefetch"]
    assert [prefetch.using for prefetch in prefetches] == ["dense", "sparse"]
    assert _visual_posts(mock_httpx_client) == []
    retrieved_ids = [call.kwargs["ids"] for call in metadata_db.client.retrieve.call_args_list]
    assert retrieved_ids == [["model-identity-confluence_documents"]]


@pytest.mark.asyncio
async def test_upsert_batch_visual_attaches_vectors_to_image_parts_only(mock_qdrant_client, mock_httpx_client):
    _mock_collections_exist(mock_qdrant_client, DOCUMENTS_COLLECTION, exists=True)
    with documents_service(visual_enabled=True) as (service, metadata_db):
        parts = [
            _document_part(part_index=0, image=base64.b64encode(b"png-bytes").decode("ascii")),
            _document_part(part_index=1),
        ]
        await service.upsert_batch(parts, ensure=False)

    points = mock_qdrant_client.upsert.call_args.kwargs["points"]
    assert set(points[0].vector.keys()) == {"dense", "sparse", "visual"}
    assert points[0].vector["visual"] == [0.3, 0.4]
    assert set(points[1].vector.keys()) == {"dense", "sparse"}
    # Exactly the part-0 image was sent to the visual endpoint.
    image_posts = [c for c in mock_httpx_client.post.call_args_list if c.args[0].endswith("/embed-page-image")]
    assert len(image_posts) == 1
    assert image_posts[0].kwargs["json"] == {"images": [base64.b64encode(b"png-bytes").decode("ascii")]}
    identity_ids = [call.kwargs["points"][0].id for call in metadata_db.client.upsert.call_args_list]
    assert "model-identity-visual-confluence_documents" in identity_ids


@pytest.mark.asyncio
async def test_upsert_batch_visual_mode_without_images_makes_no_visual_calls(mock_qdrant_client, mock_httpx_client):
    _mock_collections_exist(mock_qdrant_client, DOCUMENTS_COLLECTION, exists=True)
    with documents_service(visual_enabled=True):
        service = VectorDbService(DOCUMENTS_COLLECTION)
        await service.upsert_batch([_document_part(part_index=0)], ensure=False)

    image_posts = [c for c in mock_httpx_client.post.call_args_list if c.args[0].endswith("/embed-page-image")]
    assert image_posts == []


@pytest.mark.asyncio
async def test_upsert_batch_without_visual_makes_no_visual_calls(mock_qdrant_client, mock_httpx_client):
    _mock_collections_exist(mock_qdrant_client, DOCUMENTS_COLLECTION, exists=True)
    with documents_service(visual_enabled=False) as (service, _metadata_db):
        parts = [
            _document_part(part_index=0, image=base64.b64encode(b"png-bytes").decode("ascii")),
            _document_part(part_index=1),
        ]
        await service.upsert_batch(parts, ensure=False)

    points = mock_qdrant_client.upsert.call_args.kwargs["points"]
    assert all(set(point.vector.keys()) == {"dense", "sparse"} for point in points)
    assert _visual_posts(mock_httpx_client) == []
    # Matching identity: nothing stored, and no visual identity record in particular.
    assert not any(
        call.kwargs["points"][0].id == "model-identity-visual-confluence_documents"
        for call in mock_qdrant_client.upsert.call_args_list
    )


@pytest.mark.asyncio
async def test_visual_model_identity_mismatch_refuses(service_with_metadata_db):
    issues_db, metadata_db = service_with_metadata_db
    stored = MagicMock()
    stored.payload = {"model": "old-visual-model"}
    metadata_db.client.retrieve.return_value = [stored]

    with pytest.raises(RuntimeError, match=r"old-visual-model.*new-visual-model"):
        await issues_db._verify_model_identity("new-visual-model", visual=True)


@pytest.mark.asyncio
async def test_embed_page_images_batches_by_service_batch_limit(vector_db_service, mock_httpx_client):
    with patch("common.services.vector_db_service.config.EmbeddingServiceConfig") as mock_embedding_config:
        mock_embedding_config.MAX_BATCH_SIZE = 1
        vectors, model = await vector_db_service._embed_page_images([b"a", b"b", b"c"])

    assert vectors == [[0.3, 0.4], [0.3, 0.4], [0.3, 0.4]]
    assert model == "visual-model"
    assert mock_httpx_client.post.call_count == 3
    assert all(call.args[0].endswith("/embed-page-image") for call in mock_httpx_client.post.call_args_list)

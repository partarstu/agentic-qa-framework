# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the embedding service's WS6 surface: backends, warm-up and endpoints.

Every ML library and the FlagEmbedding model are mocked; the tests assert the endpoint
contracts, the single-flight warm-up, disabled-backend errors, input limits and auth.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# The Docker image copies services/embedding_service/ to /app/embedding_service, so the
# service's own imports use the flat "embedding_service.backends" layout. Mirror the same
# layout by putting services/ on the path (embedding_service is a namespace package).
SERVICES_DIR = Path(__file__).resolve().parents[2] / "services"
if str(SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICES_DIR))


@pytest.fixture
def mock_text_backend():
    """A loaded fake text backend returning deterministic dense and sparse output."""
    from embedding_service.backends.base import SparseVector, TextEmbedding

    backend = MagicMock()
    backend.name = "text"
    backend.is_loaded.return_value = True
    backend.embed_document_texts.return_value = [TextEmbedding(dense=[0.1, 0.2], sparse=SparseVector(indices=[5], values=[0.9]))]
    backend.embed_query_texts.return_value = [TextEmbedding(dense=[0.3, 0.4], sparse=SparseVector(indices=[7], values=[0.8]))]
    return backend


@pytest.fixture
def app_with_backend(mock_text_backend):
    """The service app with the registry mocked to the fake backend."""
    with patch("embedding_service.main._registry") as mock_registry:
        mock_registry.enabled_names = ("text",)
        mock_registry.is_enabled.side_effect = lambda name: name == "text"
        mock_registry.get_loaded = AsyncMock(return_value=mock_text_backend)
        mock_registry.warm_up = AsyncMock()

        from embedding_service import main as service_main

        yield service_main, mock_registry


@pytest.fixture
def client(app_with_backend):
    service_main, _ = app_with_backend
    with TestClient(service_main.app) as test_client:
        yield test_client


class TestEndpoints:
    def test_embed_document_text_returns_dense_and_sparse(self, client):
        response = client.post("/embed-document-text", json={"texts": ["hello"]})
        assert response.status_code == 200
        body = response.json()
        assert len(body["embeddings"]) == 1
        assert body["embeddings"][0]["dense"] == [0.1, 0.2]
        assert body["embeddings"][0]["sparse"] == {"indices": [5], "values": [0.9]}

    def test_embed_query_text_uses_query_backend_call(self, client, mock_text_backend):
        response = client.post("/embed-query-text", json={"texts": ["hello"]})
        assert response.status_code == 200
        mock_text_backend.embed_query_texts.assert_called_once_with(["hello"])
        assert response.json()["embeddings"][0]["dense"] == [0.3, 0.4]

    def test_batch_texts_return_one_embedding_each(self, client, mock_text_backend):
        from embedding_service.backends.base import SparseVector, TextEmbedding

        mock_text_backend.embed_document_texts.return_value = [
            TextEmbedding(dense=[0.1], sparse=SparseVector()) for _ in range(2)
        ]
        response = client.post("/embed-document-text", json={"texts": ["a", "b"]})
        assert response.status_code == 200
        assert len(response.json()["embeddings"]) == 2

    def test_empty_batch_rejected(self, client):
        response = client.post("/embed-document-text", json={"texts": []})
        assert response.status_code == 422

    def test_batch_over_limit_rejected(self, client):
        with patch("embedding_service.main.config.EmbeddingServiceConfig") as mock_config:
            mock_config.MAX_BATCH_SIZE = 2
            mock_config.MAX_TEXT_LENGTH = 1000
            response = client.post("/embed-document-text", json={"texts": ["a", "b", "c"]})
        assert response.status_code == 422
        assert "exceeds the limit of 2" in response.json()["detail"]

    def test_text_over_length_limit_rejected(self, client):
        with patch("embedding_service.main.config.EmbeddingServiceConfig") as mock_config:
            mock_config.MAX_BATCH_SIZE = 10
            mock_config.MAX_TEXT_LENGTH = 5
            response = client.post("/embed-document-text", json={"texts": ["too long text"]})
        assert response.status_code == 422
        assert "exceeding the limit of 5" in response.json()["detail"]

    def test_disabled_backend_returns_clear_error(self, client, mock_text_backend):
        with patch("embedding_service.main._registry") as mock_registry:
            mock_registry.is_enabled.return_value = False
            from embedding_service import main as service_main

            service_main._registry = mock_registry
            response = client.post("/embed-document-text", json={"texts": ["hello"]})
        assert response.status_code == 404
        assert "not enabled" in response.json()["detail"]

    def test_auth_required_when_key_configured(self, app_with_backend):
        service_main, _ = app_with_backend
        with patch.object(service_main.config, "INTERNAL_SERVICE_API_KEY", "secret"):
            test_client = TestClient(service_main.app)
            response = test_client.post("/embed-document-text", json={"texts": ["hello"]})
            assert response.status_code == 401

            response = test_client.post(
                "/embed-document-text", json={"texts": ["hello"]}, headers={"X-API-Key": "secret"}
            )
            assert response.status_code == 200

    def test_health_is_liveness_only(self, client, mock_text_backend):
        """Liveness must not load models; readiness must."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        mock_text_backend.is_loaded.assert_not_called()

    def test_ready_reports_backend_state(self, client, mock_text_backend):
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json()["backends"] == ["text"]

    def test_ready_fails_when_backend_cannot_load(self, client):
        with patch("embedding_service.main._registry") as mock_registry:
            mock_registry.enabled_names = ("text",)
            mock_registry.get_loaded = AsyncMock(side_effect=RuntimeError("model file missing"))
            from embedding_service import main as service_main

            service_main._registry = mock_registry
            response = client.get("/ready")
        assert response.status_code == 503
        assert "text" in response.json()["detail"]


class TestWarmUp:
    async def test_warm_up_loads_each_backend_once(self):
        from embedding_service.backends.registry import BackendRegistry

        backend = MagicMock()
        backend.is_loaded.return_value = False
        backend.load.side_effect = lambda: setattr(backend.is_loaded, "return_value", True)
        registry = BackendRegistry({"text": backend})

        await asyncio.gather(registry.warm_up(), registry.warm_up())

        backend.load.assert_called_once()

    async def test_warm_up_skips_loaded_backends(self):
        from embedding_service.backends.registry import BackendRegistry

        backend = MagicMock()
        backend.is_loaded.return_value = True
        registry = BackendRegistry({"text": backend})

        await registry.warm_up()

        backend.load.assert_not_called()

    async def test_get_loaded_awaits_warm_up_when_not_loaded(self):
        from embedding_service.backends.registry import BackendRegistry

        backend = MagicMock()
        backend.is_loaded.return_value = False
        registry = BackendRegistry({"text": backend})

        loaded = await registry.get_loaded("text")

        assert loaded is backend
        backend.load.assert_called_once()

    async def test_get_loaded_unknown_backend_raises(self):
        from embedding_service.backends.registry import BackendRegistry

        registry = BackendRegistry({})
        with pytest.raises(KeyError):
            await registry.get_loaded("text")

    def test_create_registry_rejects_unknown_backend(self):
        from embedding_service.backends.registry import create_registry

        with pytest.raises(ValueError, match="Unknown embedding backend"):
            create_registry(("visual",))


class TestModuleImport:
    def test_importing_service_module_does_not_import_ml_libraries(self):
        """The service module must stay importable without ML libraries (plan WS6)."""
        blocked = ["FlagEmbedding", "torch", "transformers", "sentence_transformers"]
        for module_name in blocked:
            sys.modules.pop(module_name, None)

        import importlib

        import embedding_service.main as service_main

        importlib.reload(service_main)
        for module_name in blocked:
            assert module_name not in sys.modules, f"importing the service pulled in {module_name}"

    def test_create_registry_imports_backend_lazily(self):
        """No ML library is imported until create_registry constructs the text backend."""
        sys.modules.pop("FlagEmbedding", None)
        from embedding_service.backends import registry as registry_module

        _ = registry_module.create_registry  # module import alone is ML-free
        assert "FlagEmbedding" not in sys.modules

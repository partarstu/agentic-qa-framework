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
    backend.model_name.return_value = "test-model"
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
            create_registry(("bogus",))

    def test_create_registry_accepts_visual_backend(self):
        from embedding_service.backends.registry import create_registry

        with patch("config.EmbeddingServiceConfig.VISUAL_MODEL_NAME", "BAAI/BGE-VL-base"):
            registry = create_registry(("text", "visual"))

        assert registry.enabled_names == ("text", "visual")

    def test_create_registry_visual_requires_model_name(self):
        from embedding_service.backends.registry import create_registry

        with (
            patch("config.EmbeddingServiceConfig.VISUAL_MODEL_NAME", None),
            pytest.raises(ValueError, match="EMBEDDING_VISUAL_MODEL"),
        ):
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

    def test_visual_backend_import_and_construction_are_ml_free(self, monkeypatch):
        """Constructing the visual backend (registry incl.) must not import its ML library."""
        monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)
        from embedding_service.backends import registry as registry_module

        with patch("config.EmbeddingServiceConfig.VISUAL_MODEL_NAME", "BAAI/BGE-VL-base"):
            registry_module.create_registry(("visual",))

        assert "sentence_transformers" not in sys.modules


def _tiny_png() -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (2, 2)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_base_backend_visual_methods_are_not_implemented():
    from embedding_service.backends.base import EmbeddingBackend

    backend = EmbeddingBackend()
    with pytest.raises(NotImplementedError):
        backend.embed_page_images([b"png"])
    with pytest.raises(NotImplementedError):
        backend.embed_visual_query_texts(["query"])


def _tiny_png_b64() -> str:
    import base64

    return base64.b64encode(_tiny_png()).decode("ascii")


class TestVisualBackend:
    def _loaded_backend(self, local_model: bool):
        # The conftest stub may have been popped by an earlier lazy-import test, so the
        # fake sentence_transformers module is scoped to this test via patch.dict.
        stub = MagicMock()
        with patch.dict(sys.modules, {"sentence_transformers": stub}):
            from embedding_service.backends.visual_backend import BgeVlVisualBackend

            backend = BgeVlVisualBackend()
            with (
                patch("config.EmbeddingServiceConfig.VISUAL_MODEL_NAME", "BAAI/BGE-VL-base"),
                patch("config.EmbeddingServiceConfig.VISUAL_MODEL_PATH", "/models/visual"),
                patch("os.path.isdir", return_value=local_model),
                patch("os.listdir", return_value=["model.safetensors"] if local_model else []),
            ):
                backend.load()
        return backend, stub.SentenceTransformer

    def test_load_uses_local_copy_when_present(self):
        backend, sentence_transformer = self._loaded_backend(local_model=True)

        sentence_transformer.assert_called_once_with("/models/visual", trust_remote_code=True)
        assert backend.is_loaded()

    def test_load_falls_back_to_the_configured_model_name(self):
        with patch.dict(sys.modules, {"sentence_transformers": MagicMock()}):
            from embedding_service.backends.visual_backend import BgeVlVisualBackend

            backend = BgeVlVisualBackend()
            with (
                patch("config.EmbeddingServiceConfig.VISUAL_MODEL_NAME", "BAAI/BGE-VL-base"),
                patch("config.EmbeddingServiceConfig.VISUAL_MODEL_PATH", "/models/visual"),
                patch("os.path.isdir", return_value=False),
            ):
                backend.load()
                sentence_transformer = sys.modules["sentence_transformers"].SentenceTransformer

        sentence_transformer.assert_called_once_with("BAAI/BGE-VL-base", trust_remote_code=True)
        assert backend.is_loaded()

        with patch("config.EmbeddingServiceConfig.VISUAL_MODEL_NAME", "BAAI/BGE-VL-base"):
            assert backend.model_name() == "BAAI/BGE-VL-base"

    def test_embed_page_images_returns_one_vector_per_image(self):
        backend, _ = self._loaded_backend(local_model=False)
        vector = MagicMock()
        vector.tolist.return_value = [0.5, 0.5]
        backend._model.encode.return_value = [vector]

        result = backend.embed_page_images([_tiny_png()])

        assert result == [[0.5, 0.5]]
        (pil_images,), _ = backend._model.encode.call_args
        assert len(pil_images) == 1

    def test_embed_visual_query_texts_returns_one_vector_per_text(self):
        backend, _ = self._loaded_backend(local_model=False)
        vector = MagicMock()
        vector.tolist.return_value = [0.6, 0.6]
        backend._model.encode.return_value = [vector]

        result = backend.embed_visual_query_texts(["diagram of login flow"])

        assert result == [[0.6, 0.6]]
        backend._model.encode.assert_called_once_with(["diagram of login flow"])


@pytest.fixture
def mock_visual_backend():
    backend = MagicMock()
    backend.name = "visual"
    backend.is_loaded.return_value = True
    backend.model_name.return_value = "BAAI/BGE-VL-base"
    backend.embed_page_images.return_value = [[0.5, 0.5]]
    backend.embed_visual_query_texts.return_value = [[0.6, 0.6]]
    return backend


@pytest.fixture
def visual_app_with_backends(mock_text_backend, mock_visual_backend):
    """The service app with the registry mocked to the text and visual backends."""
    backends = {"text": mock_text_backend, "visual": mock_visual_backend}

    with patch("embedding_service.main._registry") as mock_registry:
        mock_registry.enabled_names = ("text", "visual")
        mock_registry.is_enabled.side_effect = lambda name: name in backends
        mock_registry.get_loaded = AsyncMock(side_effect=lambda name: backends[name])
        mock_registry.warm_up = AsyncMock()

        from embedding_service import main as service_main

        yield service_main, mock_registry, mock_visual_backend


@pytest.fixture
def visual_client(visual_app_with_backends):
    service_main, _, _ = visual_app_with_backends
    with TestClient(service_main.app) as test_client:
        yield test_client


class TestVisualEndpoints:
    def test_embed_page_image_returns_vector_and_model(self, visual_client, mock_visual_backend):
        response = visual_client.post("/embed-page-image", json={"images": [_tiny_png_b64()]})

        assert response.status_code == 200
        body = response.json()
        assert body["vectors"] == [[0.5, 0.5]]
        assert body["model"] == "BAAI/BGE-VL-base"
        images = mock_visual_backend.embed_page_images.call_args.args[0]
        assert images == [_tiny_png()]

    def test_embed_page_image_accepts_batches(self, visual_client, mock_visual_backend):
        mock_visual_backend.embed_page_images.return_value = [[0.5], [0.5]]

        response = visual_client.post(
            "/embed-page-image", json={"images": [_tiny_png_b64(), _tiny_png_b64()]}
        )

        assert response.status_code == 200
        assert len(response.json()["vectors"]) == 2

    def test_embed_page_image_rejects_oversized_image(self, visual_client):
        with patch("embedding_service.main.config.EmbeddingServiceConfig") as mock_config:
            mock_config.MAX_BATCH_SIZE = 10
            mock_config.MAX_IMAGE_BYTES = 4
            response = visual_client.post("/embed-page-image", json={"images": [_tiny_png_b64()]})

        assert response.status_code == 422
        assert "exceeds the limit of 4" in response.json()["detail"]

    def test_embed_page_image_rejects_batch_over_limit(self, visual_client):
        with patch("embedding_service.main.config.EmbeddingServiceConfig") as mock_config:
            mock_config.MAX_BATCH_SIZE = 1
            mock_config.MAX_IMAGE_BYTES = 10_000_000
            response = visual_client.post(
                "/embed-page-image", json={"images": [_tiny_png_b64(), _tiny_png_b64()]}
            )

        assert response.status_code == 422
        assert "exceeds the limit of 1" in response.json()["detail"]

    def test_embed_page_image_rejects_invalid_base64(self, visual_client):
        response = visual_client.post("/embed-page-image", json={"images": ["not base64!!!"]})

        assert response.status_code == 422
        assert "not valid base64" in response.json()["detail"]

    def test_embed_page_image_rejects_non_image_bytes(self, visual_client, mock_visual_backend):
        from PIL import UnidentifiedImageError

        mock_visual_backend.embed_page_images.side_effect = UnidentifiedImageError("not an image")

        response = visual_client.post(
            "/embed-page-image", json={"images": [_tiny_png_b64()]}
        )

        assert response.status_code == 422
        assert "not a valid image" in response.json()["detail"]

    def test_embed_visual_query_text_returns_vector_and_model(self, visual_client, mock_visual_backend):
        response = visual_client.post("/embed-visual-query-text", json={"texts": ["login diagram"]})

        assert response.status_code == 200
        body = response.json()
        assert body["vectors"] == [[0.6, 0.6]]
        assert body["model"] == "BAAI/BGE-VL-base"
        mock_visual_backend.embed_visual_query_texts.assert_called_once_with(["login diagram"])

    def test_embed_visual_query_text_rejects_over_limit_batch(self, visual_client):
        with patch("embedding_service.main.config.EmbeddingServiceConfig") as mock_config:
            mock_config.MAX_BATCH_SIZE = 2
            mock_config.MAX_TEXT_LENGTH = 1000
            response = visual_client.post("/embed-visual-query-text", json={"texts": ["a", "b", "c"]})

        assert response.status_code == 422
        assert "exceeds the limit of 2" in response.json()["detail"]

    def test_disabled_visual_backend_returns_clear_error(self, visual_app_with_backends):
        service_main, mock_registry, _ = visual_app_with_backends
        mock_registry.is_enabled.side_effect = lambda name: name == "text"
        with TestClient(service_main.app) as client:
            response = client.post("/embed-page-image", json={"images": [_tiny_png_b64()]})
            assert response.status_code == 404
            assert "Backend 'visual' is not enabled." in response.json()["detail"]

            response = client.post("/embed-visual-query-text", json={"texts": ["login diagram"]})
            assert response.status_code == 404
            assert "Backend 'visual' is not enabled." in response.json()["detail"]

    def test_visual_endpoints_auth_required_when_key_configured(self, visual_app_with_backends):
        service_main, _, _ = visual_app_with_backends
        with patch.object(service_main.config, "INTERNAL_SERVICE_API_KEY", "secret"):
            test_client = TestClient(service_main.app)
            assert test_client.post("/embed-page-image", json={"images": [_tiny_png_b64()]}).status_code == 401
            assert test_client.post("/embed-visual-query-text", json={"texts": ["q"]}).status_code == 401

            authorized = {"X-API-Key": "secret"}
            assert (
                test_client.post(
                    "/embed-page-image", json={"images": [_tiny_png_b64()]}, headers=authorized
                ).status_code
                == 200
            )
            assert (
                test_client.post(
                    "/embed-visual-query-text", json={"texts": ["q"]}, headers=authorized
                ).status_code
                == 200
            )

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
import hmac
import os
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

# The Docker image serves this package from /app/embedding_service with config.py and common/
# next to it. Running the file directly (python services/embedding_service/main.py) puts only
# the package directory itself on sys.path, so add both the parent (flat package layout) and
# the repository root (config, common) for the imports to resolve.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PACKAGE_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PACKAGE_PARENT)
if _REPO_ROOT not in sys.path:
    sys.path.append(_REPO_ROOT)

from embedding_service.backends.registry import create_registry  # noqa: E402

import config  # noqa: E402
from common import utils  # noqa: E402

logger = utils.get_logger("embedding_service")

# The registry is created from configuration at import time; backend models load lazily.
_registry = create_registry(config.EmbeddingServiceConfig.BACKENDS)

# Keeps references to background warm-up tasks so they are never garbage-collected mid-flight.
_WARM_UP_TASKS: list[asyncio.Task] = []


async def _warm_up_backends() -> None:
    """Load every enabled backend in the background, so requests can arrive during warm-up."""
    logger.info("Starting warm-up of embedding backends: %s", _registry.enabled_names)
    _WARM_UP_TASKS.append(asyncio.create_task(_registry.warm_up()))


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await _warm_up_backends()
    yield
    for task in _WARM_UP_TASKS:
        task.cancel()


app = FastAPI(title="Embedding Service", lifespan=_lifespan)


def _require_service_auth(x_api_key: str | None = Header(default=None)) -> None:
    """Enforce the shared internal-service secret when one is configured.

    When INTERNAL_SERVICE_API_KEY is unset the service stays open (it is expected to be
    reachable only on a private network); when set, a matching X-API-Key header is required.
    """
    expected = config.INTERNAL_SERVICE_API_KEY
    if expected and (not x_api_key or not hmac.compare_digest(x_api_key, expected)):
        raise HTTPException(status_code=401, detail="Unauthorized")


class TextEmbeddingRequest(BaseModel):
    texts: list[str] = Field(min_length=1)


class SparseVectorResponse(BaseModel):
    indices: list[int]
    values: list[float]


class TextEmbeddingResponse(BaseModel):
    dense: list[float]
    sparse: SparseVectorResponse


class TextEmbeddingsResponse(BaseModel):
    embeddings: list[TextEmbeddingResponse]
    model: str


@app.get("/health")
def health_check():
    """Liveness: the process is up, independent of model loading."""
    return {"status": "ok"}


@app.get("/ready")
async def readiness_check():
    """Readiness: every enabled backend is loaded. The Cloud Run startup probe targets this.

    Deliberately unauthenticated: the startup probe cannot send headers, so requiring the
    internal API key here would break the deployment (liveness stays open the same way).
    """
    missing = [name for name in _registry.enabled_names if not await _is_backend_ready(name)]
    if missing:
        raise HTTPException(status_code=503, detail=f"Backends not ready: {missing}")
    return {"status": "ready", "backends": list(_registry.enabled_names)}


async def _is_backend_ready(name: str) -> bool:
    try:
        await _registry.get_loaded(name)
        return True
    except Exception:
        logger.exception("Backend '%s' failed to load.", name)
        return False


def _validate_texts(texts: list[str]) -> None:
    max_batch = config.EmbeddingServiceConfig.MAX_BATCH_SIZE
    max_length = config.EmbeddingServiceConfig.MAX_TEXT_LENGTH
    if len(texts) > max_batch:
        raise HTTPException(status_code=422, detail=f"Batch of {len(texts)} exceeds the limit of {max_batch} texts.")
    for index, text in enumerate(texts):
        if len(text) > max_length:
            raise HTTPException(
                status_code=422,
                detail=f"Text at index {index} is {len(text)} characters long, exceeding the limit of {max_length}.",
            )


async def _embed_texts(texts: list[str], query: bool):
    """Validate, load the text backend (awaiting warm-up) and encode off the event loop."""
    _validate_texts(texts)
    if not _registry.is_enabled("text"):
        raise HTTPException(status_code=404, detail="Backend 'text' is not enabled.")
    backend = await _registry.get_loaded("text")
    model = backend.model_name()
    encode = backend.embed_query_texts if query else backend.embed_document_texts
    embeddings = await asyncio.to_thread(encode, texts)
    return embeddings, model


def _to_response(embeddings, model: str) -> TextEmbeddingsResponse:
    return TextEmbeddingsResponse(
        model=model,
        embeddings=[
            TextEmbeddingResponse(
                dense=embedding.dense,
                sparse=SparseVectorResponse(indices=embedding.sparse.indices, values=embedding.sparse.values),
            )
            for embedding in embeddings
        ],
    )


@app.post("/embed-document-text", response_model=TextEmbeddingsResponse)
async def embed_document_texts(
    request: TextEmbeddingRequest, _: None = Depends(_require_service_auth)
) -> TextEmbeddingsResponse:
    """Embed document content texts; returns a dense vector and sparse weights per input."""
    embeddings, model = await _embed_texts(request.texts, query=False)
    return _to_response(embeddings, model)


@app.post("/embed-query-text", response_model=TextEmbeddingsResponse)
async def embed_query_texts(
    request: TextEmbeddingRequest, _: None = Depends(_require_service_auth)
) -> TextEmbeddingsResponse:
    """Embed query texts, applying the model's query instruction when it has one."""
    embeddings, model = await _embed_texts(request.texts, query=True)
    return _to_response(embeddings, model)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

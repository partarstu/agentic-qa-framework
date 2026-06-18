# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import hmac
import os

import torch
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

import config
from common import utils

os.environ["TOKENIZERS_PARALLELISM"] = "true"

logger = utils.get_logger("embedding_service")

app = FastAPI(title="Embedding Service")


def _require_service_auth(x_api_key: str | None = Header(default=None)) -> None:
    """Enforce the shared internal-service secret when one is configured.

    When INTERNAL_SERVICE_API_KEY is unset the service stays open (it is expected to be
    reachable only on a private network); when set, a matching X-API-Key header is required.
    """
    expected = config.INTERNAL_SERVICE_API_KEY
    if expected and (not x_api_key or not hmac.compare_digest(x_api_key, expected)):
        raise HTTPException(status_code=401, detail="Unauthorized")

# Model configuration - model is loaded lazily to avoid memory issues during worker forking
_model_name = getattr(config.QdrantConfig, "EMBEDDING_MODEL", "jinaai/jina-embeddings-v3")
_model_path = getattr(config.QdrantConfig, "EMBEDDING_MODEL_PATH", None)
_embedding_model: SentenceTransformer | None = None


def _get_embedding_model() -> SentenceTransformer:
    """
    Lazily load the embedding model on first use.

    This prevents the model from being loaded during module import,
    which would cause memory issues with Gunicorn's pre-fork worker model.
    The model is only loaded once per worker process.
    """
    global _embedding_model
    if _embedding_model is None:
        torch.set_num_threads(os.cpu_count() or 1)
        logger.info(f"Initializing embedding service with model: {_model_name}")

        if _model_path and os.path.exists(_model_path) and os.listdir(_model_path):
            logger.info(f"Loading embedding model from local path: {_model_path}")
            _embedding_model = SentenceTransformer(_model_path)
        else:
            logger.info(f"Model not found locally at {_model_path}, downloading: {_model_name}")
            _embedding_model = SentenceTransformer(_model_name)
        logger.info("Embedding model loaded successfully")
    return _embedding_model


class EmbeddingRequest(BaseModel):
    text: str


class EmbeddingResponse(BaseModel):
    embedding: list[float]


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/embed", response_model=EmbeddingResponse)
async def get_embedding(request: EmbeddingRequest, _: None = Depends(_require_service_auth)):
    try:
        model = _get_embedding_model()
        embedding = model.encode(request.text)
        return EmbeddingResponse(embedding=embedding.tolist())
    except Exception:
        logger.exception("Error generating embedding.")
        raise HTTPException(status_code=500, detail="Internal server error")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

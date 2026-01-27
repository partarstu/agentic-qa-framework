import os

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

import config
from common import utils

logger = utils.get_logger("embedding_service")

app = FastAPI(title="Embedding Service")

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
        logger.info(f"Initializing embedding service with model: {_model_name}")
        # Use tokenizer_kwargs to fix Mistral tokenizer regex pattern issue
        # See: https://huggingface.co/mistralai/Mistral-Small-3.1-24B-Instruct-2503/discussions/84
        tokenizer_kwargs = {"fix_mistral_regex": True}

        if _model_path and os.path.exists(_model_path) and os.listdir(_model_path):
            logger.info(f"Loading embedding model from local path: {_model_path}")
            _embedding_model = SentenceTransformer(_model_path, tokenizer_kwargs=tokenizer_kwargs)
        else:
            logger.info(f"Model not found locally at {_model_path}, downloading: {_model_name}")
            _embedding_model = SentenceTransformer(_model_name, tokenizer_kwargs=tokenizer_kwargs)
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
async def get_embedding(request: EmbeddingRequest):
    try:
        model = _get_embedding_model()
        embedding = model.encode(request.text)
        return EmbeddingResponse(embedding=embedding.tolist())
    except Exception as e:
        logger.exception("Error generating embedding.")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

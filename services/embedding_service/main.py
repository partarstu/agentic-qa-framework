import os
from typing import List

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import config
from sentence_transformers import SentenceTransformer
from common import utils

logger = utils.get_logger("embedding_service")

app = FastAPI(title="Embedding Service")

model_name = getattr(config.QdrantConfig, "EMBEDDING_MODEL", "jinaai/jina-embeddings-v3")
model_path = getattr(config.QdrantConfig, "EMBEDDING_MODEL_PATH", None)

logger.info(f"Initializing embedding service with model: {model_name}")

if model_path and os.path.exists(model_path) and os.listdir(model_path):
    logger.info(f"Loading embedding model from local path: {model_path}")
    embedding_model = SentenceTransformer(model_path)
else:
    logger.info(f"Model not found locally at {model_path}, downloading: {model_name}")
    embedding_model = SentenceTransformer(model_name)


class EmbeddingRequest(BaseModel):
    text: str


class EmbeddingResponse(BaseModel):
    embedding: List[float]


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/embed", response_model=EmbeddingResponse)
async def get_embedding(request: EmbeddingRequest):
    try:
        embedding = embedding_model.encode(request.text)
        return EmbeddingResponse(embedding=embedding.tolist())
    except Exception as e:
        logger.error(f"Error generating embedding: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

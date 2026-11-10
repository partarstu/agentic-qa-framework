# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Text backend: dense embeddings from the text encoder of EmbeddingGemma 2.

The ML library (sentence-transformers) is imported only inside ``load``, so importing this
module stays cheap and the service module never pulls ML libraries at import time.
"""

import os
from pathlib import Path

from embedding_service.backends.base import EmbeddingBackend, TextEmbedding

import config

# The model's own retrieval prompts (config_sentence_transformers.json); a document has no title here,
# because the ingestion already puts its breadcrumb into the text.
_QUERY_PROMPT = "task: search result | query: "
_DOCUMENT_PROMPT = "title: none | text: "


class EmbeddingGemmaTextBackend(EmbeddingBackend):
    """Dense text embedding through EmbeddingGemma 2, loaded without its vision and audio encoders."""

    name = "text"

    def __init__(self) -> None:
        self._model = None

    def load(self) -> None:
        import torch
        from huggingface_hub import snapshot_download
        from sentence_transformers import SentenceTransformer

        os.environ.setdefault("TOKENIZERS_PARALLELISM", "true")
        if _model_available_locally():
            model_path = _configured_model_path()
        else:
            model_path = snapshot_download(
                _configured_model_name(), revision=config.EmbeddingServiceConfig.TEXT_MODEL_REVISION
            )
        self._model = SentenceTransformer(
            model_path,
            device="cpu",
            # float16 overflows the model's activation range and yields NaN or degraded vectors silently.
            model_kwargs={"torch_dtype": torch.float32},
            config_kwargs={"vision_config": None, "audio_config": None},
        )

    def is_loaded(self) -> bool:
        return self._model is not None

    def model_name(self) -> str:
        return _configured_model_name()

    def embed_document_texts(self, texts: list[str]) -> list[TextEmbedding]:
        return self._encode(texts, _DOCUMENT_PROMPT)

    def embed_query_texts(self, texts: list[str]) -> list[TextEmbedding]:
        return self._encode(texts, _QUERY_PROMPT)

    def _encode(self, texts: list[str], prompt: str) -> list[TextEmbedding]:
        vectors = self._model.encode(texts, prompt=prompt, normalize_embeddings=True, convert_to_numpy=True)
        return [TextEmbedding(dense=row) for row in vectors.tolist()]


def _configured_model_name() -> str:
    return config.EmbeddingServiceConfig.TEXT_MODEL_NAME


def _configured_model_path() -> str:
    return config.EmbeddingServiceConfig.TEXT_MODEL_PATH


def _model_available_locally() -> bool:
    path = Path(_configured_model_path())
    return path.is_dir() and any(path.iterdir())

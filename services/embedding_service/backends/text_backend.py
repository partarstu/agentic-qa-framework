# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Text backend: one multilingual model producing dense and learned-sparse output.

The BGE-M3 family produces both vectors in a single forward pass. The ML library
(FlagEmbedding) is imported only inside ``load``, so importing this module stays cheap
and the service module never pulls ML libraries at import time.
"""

import os

from embedding_service.backends.base import EmbeddingBackend, SparseVector, TextEmbedding


def _build_sparse(lexical_weights: dict) -> SparseVector:
    """Convert one lexical-weights mapping (token id -> weight) into parallel lists."""
    indices = sorted(lexical_weights)
    return SparseVector(indices=indices, values=[float(lexical_weights[token]) for token in indices])


class BgeM3TextBackend(EmbeddingBackend):
    """Dense + learned-sparse text embedding through the BGE-M3 model family."""

    name = "text"

    def __init__(self) -> None:
        self._model = None

    def load(self) -> None:
        from FlagEmbedding import BGEM3FlagModel

        os.environ.setdefault("TOKENIZERS_PARALLELISM", "true")
        model_name = _configured_model_name()
        if _model_available_locally():
            self._model = BGEM3FlagModel(_configured_model_path(), use_fp16=False)
        else:
            self._model = BGEM3FlagModel(model_name, use_fp16=False)

    def is_loaded(self) -> bool:
        return self._model is not None

    def model_name(self) -> str:
        return _configured_model_name()

    def embed_document_texts(self, texts: list[str]) -> list[TextEmbedding]:
        return self._encode(texts)

    def embed_query_texts(self, texts: list[str]) -> list[TextEmbedding]:
        return self._encode(texts)

    def _encode(self, texts: list[str]) -> list[TextEmbedding]:
        output = self._model.encode(
            texts,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        embeddings = []
        for dense_row, weights in zip(output["dense_vecs"].tolist(), output["lexical_weights"], strict=True):
            embeddings.append(TextEmbedding(dense=dense_row, sparse=_build_sparse(weights)))
        return embeddings


def _configured_model_name() -> str:
    import config

    return config.EmbeddingServiceConfig.TEXT_MODEL_NAME


def _configured_model_path() -> str:
    import config

    return config.EmbeddingServiceConfig.TEXT_MODEL_PATH


def _model_available_locally() -> bool:
    path = _configured_model_path()
    return os.path.isdir(path) and bool(os.listdir(path))

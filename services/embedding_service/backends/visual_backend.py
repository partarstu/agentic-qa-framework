# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Visual backend: one CLIP-style model embedding page images and query texts into a
shared vector space.

BGE-VL (BAAI/BGE-VL-base) emits one dense vector per image, so a page image is
represented by a single named dense vector (no multivector). sentence-transformers
and Pillow are imported only inside the methods that need them, so importing this
module stays cheap and the service module never pulls ML libraries at import time.
"""

import io
import os

from embedding_service.backends.base import EmbeddingBackend


class BgeVlVisualBackend(EmbeddingBackend):
    """Dense page-image and visual-query embeddings through the BGE-VL model family."""

    name = "visual"

    def __init__(self) -> None:
        self._model = None

    def load(self) -> None:
        from sentence_transformers import SentenceTransformer

        model_name = _configured_model_name()
        if _model_available_locally():
            self._model = SentenceTransformer(_configured_model_path(), trust_remote_code=True)
        else:
            self._model = SentenceTransformer(model_name, trust_remote_code=True)

    def is_loaded(self) -> bool:
        return self._model is not None

    def model_name(self) -> str:
        return _configured_model_name()

    def embed_page_images(self, images: list[bytes]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.encode(_open_images(images))]

    def embed_visual_query_texts(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.encode(texts)]


def _open_images(images: list[bytes]) -> list:
    """Decodes PNG bytes into fully loaded PIL images (decode happens off the event loop)."""
    import PIL.Image

    pil_images = []
    for image_bytes in images:
        image = PIL.Image.open(io.BytesIO(image_bytes))
        image.load()
        pil_images.append(image)
    return pil_images


def _configured_model_name() -> str:
    import config

    return config.EmbeddingServiceConfig.VISUAL_MODEL_NAME


def _configured_model_path() -> str:
    import config

    return config.EmbeddingServiceConfig.VISUAL_MODEL_PATH


def _model_available_locally() -> bool:
    path = _configured_model_path()
    return os.path.isdir(path) and bool(os.listdir(path))

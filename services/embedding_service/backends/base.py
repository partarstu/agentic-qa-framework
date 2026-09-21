# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Embedding backends, one per model family.

Each backend is imported and loaded lazily: importing this package (or the service
module) must never import an ML library.
"""

from dataclasses import dataclass, field


@dataclass(slots=True)
class SparseVector:
    """Learned-sparse output of one text: token id to weight."""

    indices: list[int] = field(default_factory=list)
    values: list[float] = field(default_factory=list)


@dataclass(slots=True)
class TextEmbedding:
    """Dense and learned-sparse representation of one text, produced in a single pass."""

    dense: list[float] = field(default_factory=list)
    sparse: SparseVector = field(default_factory=SparseVector)


class EmbeddingBackend:
    """A lazily loaded embedding backend. Subclasses import their ML libraries in ``load``."""

    name: str = "backend"

    def load(self) -> None:
        """Load the model. Imports of ML libraries happen here, never at module import."""

    def is_loaded(self) -> bool:
        """Whether ``load`` has completed successfully."""
        raise NotImplementedError

    def model_name(self) -> str:
        """Identity of the model producing this backend's vectors, recorded by clients."""
        raise NotImplementedError

    def embed_document_texts(self, texts: list[str]) -> list[TextEmbedding]:
        """Embed content texts (no query instruction)."""
        raise NotImplementedError

    def embed_query_texts(self, texts: list[str]) -> list[TextEmbedding]:
        """Embed query texts, applying the model's query instruction when it has one."""
        raise NotImplementedError

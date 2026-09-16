# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Warm-up and backend registry for the embedding service (WS6).

On startup a background task loads every enabled backend. A single-flight guard makes
requests that arrive during warm-up wait for the same load instead of starting a second
one.
"""

import asyncio

from embedding_service.backends.base import EmbeddingBackend


class BackendRegistry:
    """Holds the enabled backends and their warm-up state.

    The registry is created from configuration once; ``warm_up`` is called from the
    startup handler and awaited by requests that arrive before warm-up finishes.
    """

    def __init__(self, backends: dict[str, EmbeddingBackend]):
        self._backends = backends
        self._warm_up_lock = asyncio.Lock()

    @property
    def enabled_names(self) -> tuple[str, ...]:
        return tuple(self._backends)

    def is_enabled(self, name: str) -> bool:
        return name in self._backends

    async def warm_up(self) -> None:
        """Load every enabled backend once. Concurrent callers share one load."""
        async with self._warm_up_lock:
            for backend in self._backends.values():
                if not backend.is_loaded():
                    await asyncio.to_thread(backend.load)

    async def get_loaded(self, name: str) -> EmbeddingBackend:
        """Return the named backend, awaiting warm-up first when it isn't loaded yet.

        Raises:
            KeyError: When the backend isn't enabled.
        """
        backend = self._backends.get(name)
        if backend is None:
            raise KeyError(name)
        if not backend.is_loaded():
            await self.warm_up()
        return backend


def create_registry(enabled_backends: tuple[str, ...]) -> BackendRegistry:
    """Create the registry from the enabled backend names.

    The backend classes are imported lazily here, keeping module import ML-free.

    Raises:
        ValueError: When a backend name is unknown, or the visual backend is enabled
            without a configured visual model.
    """
    backends: dict[str, EmbeddingBackend] = {}
    for name in enabled_backends:
        if name == "text":
            from embedding_service.backends.text_backend import BgeM3TextBackend

            backends[name] = BgeM3TextBackend()
        elif name == "visual":
            import config

            if not config.EmbeddingServiceConfig.VISUAL_MODEL_NAME:
                raise ValueError("Backend 'visual' requires EMBEDDING_VISUAL_MODEL to be set.")
            from embedding_service.backends.visual_backend import BgeVlVisualBackend

            backends[name] = BgeVlVisualBackend()
        else:
            raise ValueError(f"Unknown embedding backend: '{name}'. Known backends: text, visual.")
    return BackendRegistry(backends)

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import os
import sys
from unittest.mock import MagicMock

from dotenv import dotenv_values


def _configured_google_api_key() -> str | None:
    """The real key from the environment or the .env file, before the dummy replaces it.

    Only the smoke suite uses it (see tests/smoke/conftest.py); unit tests never reach a real
    API, so they run with the dummy below.
    """
    return os.environ.get("GOOGLE_API_KEY") or dotenv_values().get("GOOGLE_API_KEY")


CONFIGURED_GOOGLE_API_KEY = _configured_google_api_key()

# Set dummy API keys, so that no unit test can reach a real provider.
os.environ["OPENAI_API_KEY"] = "dummy"
os.environ["GOOGLE_API_KEY"] = "dummy"

# Point the vector DB at localhost like CI does: a developer's .env may name a real remote
# instance, and unit tests must never read from or write to it. Nothing serves the port
# locally, so any accidental real call fails fast instead of reaching the remote.
os.environ["QDRANT_URL"] = "http://localhost:6333"
os.environ.pop("QDRANT_API_KEY", None)

# Provide dummy auth configuration so the now fail-closed auth has valid settings under test,
# and keep prompt-injection checks off by default (tests that need them opt in explicitly).
os.environ.setdefault("ORCHESTRATOR_API_KEY", "test-orchestrator-key")
os.environ.setdefault("DASHBOARD_USERNAME", "test-admin")
os.environ.setdefault("DASHBOARD_PASSWORD_HASH", "$2b$12$1xngtpKa0L19xVXRr65je.ahTTd1j/CHHa8iC8Kmhn4sqRpQAZb9u")
os.environ.setdefault("DASHBOARD_JWT_SECRET", "test-jwt-secret-not-for-production")
os.environ.setdefault("PROMPT_INJECTION_CHECK_ENABLED", "False")

# Mock sentence_transformers to avoid loading models during test collection
mock_sentence_transformers = MagicMock()
sys.modules["sentence_transformers"] = mock_sentence_transformers

import pytest  # noqa: E402

# Add the project root to sys.path so that imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def with_real_lock_lifecycle(lock_store: MagicMock) -> MagicMock:
    """Binds the real ``held_for_run`` to an otherwise mocked lock store.

    The runners share that one lifecycle (verify-or-acquire, release on every exit), so a fully
    mocked lock store would stop the sync tests from covering it at all.
    """
    from functools import partial

    from common.services.sync_lock_store import SyncLockStore

    lock_store.held_for_run = partial(SyncLockStore.held_for_run, lock_store)
    return lock_store

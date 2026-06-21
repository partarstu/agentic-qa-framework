# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import os
import sys
from unittest.mock import MagicMock

# Set dummy API key for OpenAI provider
os.environ["OPENAI_API_KEY"] = "dummy"
os.environ["GOOGLE_API_KEY"] = "dummy"

# Provide dummy auth configuration so the now fail-closed auth has valid settings under test,
# and keep prompt-injection checks off by default (tests that need them opt in explicitly).
os.environ.setdefault("ORCHESTRATOR_API_KEY", "test-orchestrator-key")
os.environ.setdefault("DASHBOARD_USERNAME", "test-admin")
os.environ.setdefault("DASHBOARD_PASSWORD", "test-password")
os.environ.setdefault("DASHBOARD_JWT_SECRET", "test-jwt-secret-not-for-production")
os.environ.setdefault("PROMPT_INJECTION_CHECK_ENABLED", "False")

# Mock sentence_transformers to avoid loading models during test collection
mock_sentence_transformers = MagicMock()
sys.modules["sentence_transformers"] = mock_sentence_transformers

# Mock python-magic: importing it loads libmagic via ctypes, which segfaults on this
# platform's binary. Tests that need it patch common.attachment_handler.magic explicitly.
# Default from_file to None so content-based detection yields "no type" unless configured.
_mock_magic = MagicMock()
_mock_magic.from_file.return_value = None
sys.modules["magic"] = _mock_magic

import pytest  # noqa: E402

# Add the project root to sys.path so that imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Template for tests/conftest.py - global test configuration.

This file sets up the test environment, mocks heavy dependencies,
and provides shared fixtures.
"""

import os
import sys
from unittest.mock import MagicMock

# Set dummy API keys for test environment
os.environ["OPENAI_API_KEY"] = "dummy"
os.environ["GOOGLE_API_KEY"] = "dummy"

# Mock heavy dependencies to avoid loading during test collection
mock_sentence_transformers = MagicMock()
sys.modules["sentence_transformers"] = mock_sentence_transformers

import pytest  # noqa: E402

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

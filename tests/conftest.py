import sys
from unittest.mock import MagicMock
import os

# Set dummy API key for OpenAI provider
os.environ["OPENAI_API_KEY"] = "dummy"

# Mock sentence_transformers to avoid loading models during test collection
mock_sentence_transformers = MagicMock()
sys.modules["sentence_transformers"] = mock_sentence_transformers

import pytest

# Add the project root to sys.path so that imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
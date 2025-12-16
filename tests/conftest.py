import sys
from unittest.mock import MagicMock
import os

# Set dummy API key for OpenAI provider
os.environ["OPENAI_API_KEY"] = "dummy"

# Mock transformers before it is imported by application code
mock_transformers = MagicMock()
sys.modules["transformers"] = mock_transformers
sys.modules["transformers.pipeline"] = MagicMock()

import pytest

# Add the project root to sys.path so that imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
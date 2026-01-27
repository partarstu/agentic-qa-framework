import os
import runpy
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_transformers():
    mock = MagicMock()
    with patch.dict(sys.modules, {"transformers": mock}):
        yield mock

def test_download_enabled(mock_transformers):
    # Setup mocks
    mock_tokenizer = MagicMock()
    mock_model = MagicMock()
    mock_transformers.AutoTokenizer.from_pretrained.return_value = mock_tokenizer
    mock_transformers.AutoModelForSequenceClassification.from_pretrained.return_value = mock_model

    # We need to mock config specifically because the script does "from config import ..."
    # We can patch the config module itself if it's already loaded or force it.
    # A safe way is to mock sys.modules['config'] as well or rely on it being loaded and patch attributes.

    # Let's mock sys.modules['config'] to be sure we control what is imported
    mock_config = MagicMock()
    mock_config.PROMPT_INJECTION_CHECK_ENABLED = True
    mock_config.PROMPT_INJECTION_DETECTION_MODEL_PATH = "models/pi"
    mock_config.PROMPT_INJECTION_DETECTION_MODEL_NAME = "model-name"

    with patch.dict(sys.modules, {"config": mock_config}), \
         patch("os.path.exists", return_value=False), \
         patch("os.makedirs") as mock_makedirs:

        # Execute the script
        runpy.run_module("scripts.download_prompt_guard_model", run_name="__main__")

        # Verify interactions
        mock_makedirs.assert_called_with("models/pi")
        mock_transformers.AutoTokenizer.from_pretrained.assert_called_with("model-name")
        mock_tokenizer.save_pretrained.assert_called_with("models/pi")
        mock_transformers.AutoModelForSequenceClassification.from_pretrained.assert_called_with("model-name")
        mock_model.save_pretrained.assert_called_with("models/pi")

def test_download_disabled(mock_transformers):
    mock_config = MagicMock()
    mock_config.PROMPT_INJECTION_CHECK_ENABLED = False

    with patch.dict(sys.modules, {"config": mock_config}):
        runpy.run_module("scripts.download_prompt_guard_model", run_name="__main__")

        # Verify NO interactions
        mock_transformers.AutoTokenizer.from_pretrained.assert_not_called()

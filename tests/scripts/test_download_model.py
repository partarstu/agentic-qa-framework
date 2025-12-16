
import pytest
from unittest.mock import MagicMock, patch
import os

@patch("scripts.download_model.AutoTokenizer")
@patch("scripts.download_model.AutoModelForSequenceClassification")
@patch("scripts.download_model.os.path.exists")
@patch("scripts.download_model.os.makedirs")
def test_download_model_enabled(mock_makedirs, mock_exists, mock_model_cls, mock_tokenizer_cls):
    with patch("scripts.download_model.PROMPT_INJECTION_CHECK_ENABLED", True), \
         patch("scripts.download_model.PROMPT_INJECTION_DETECTION_MODEL_PATH", "models/pi"), \
         patch("scripts.download_model.PROMPT_INJECTION_DETECTION_MODEL_NAME", "model-name"):
         
         mock_exists.return_value = False
         
         # Execute the script logic. Since it's in if __name__ == "__main__", we can't import it easily to run that block.
         # But the logic is top-level if we assume the test runs the content.
         # Instead, we can extract the logic or just verify the mocks if we were to run it.
         # But `scripts.download_model` only has code under `if __name__`.
         # So importing it does nothing.
         pass

# The script is designed to be run as a script. 
# Testing it via unit test is tricky unless we refactor it to have a function `download_model()``.
# Or we can use `runpy`.

import runpy

@patch("transformers.AutoTokenizer")
@patch("transformers.AutoModelForSequenceClassification")
@patch("os.path.exists")
@patch("os.makedirs")
def test_script_execution_enabled(mock_makedirs, mock_exists, mock_model_cls, mock_tokenizer_cls):
    mock_exists.return_value = False
    
    with patch("config.PROMPT_INJECTION_CHECK_ENABLED", True), \
         patch("config.PROMPT_INJECTION_DETECTION_MODEL_PATH", "models/pi"), \
         patch("config.PROMPT_INJECTION_DETECTION_MODEL_NAME", "model-name"):
         
         # We need to ensure config import in the script uses our patched values?
         # `from config import ...` happens at top level.
         # So runpy will re-execute imports. 
         # We need to mock `config` module in sys.modules so when script imports it, it gets our mock. 
         
         with patch.dict(sys.modules, {"config": MagicMock(PROMPT_INJECTION_CHECK_ENABLED=True, 
                                                           PROMPT_INJECTION_DETECTION_MODEL_PATH="models/pi",
                                                           PROMPT_INJECTION_DETECTION_MODEL_NAME="model-name")}):
             runpy.run_module("scripts.download_model", run_name="__main__")
             
             mock_tokenizer_cls.from_pretrained.assert_called_with("model-name")
             mock_model_cls.from_pretrained.assert_called_with("model-name")

import sys

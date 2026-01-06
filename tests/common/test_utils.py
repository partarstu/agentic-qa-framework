
import pytest
from unittest.mock import MagicMock, patch, mock_open
import mimetypes
from pathlib import Path
import os
from pydantic_ai import BinaryContent
from common import utils

# Mock config
@pytest.fixture(autouse=True)
def mock_config(monkeypatch):
    monkeypatch.setattr("config.GOOGLE_CLOUD_LOGGING_ENABLED", False)
    monkeypatch.setattr("config.LOG_LEVEL", "INFO")

def test_get_logger_local():
    logger = utils.get_logger("test_logger")
    assert logger.name == "test_logger"
    assert logger.level == 20 # INFO

@patch("common.utils.config.GOOGLE_CLOUD_LOGGING_ENABLED", True)
@patch("google.cloud.logging.Client")
def test_get_logger_cloud(mock_client_cls):
    utils.logging_initialized = False # Reset to force re-init
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    
    logger = utils.get_logger("cloud_logger")
    mock_client.setup_logging.assert_called_once()
    assert logger.name == "cloud_logger"

def test_fetch_media_file_content_from_local_file_exists():
    with patch("pathlib.Path.is_file", return_value=True), \
         patch("pathlib.Path.read_bytes", return_value=b"test data"), \
         patch("mimetypes.guess_type", return_value=("image/png", None)):
        
        content = utils.fetch_media_file_content_from_local("test.png", "/tmp")
        assert isinstance(content, BinaryContent)
        assert content.data == b"test data"
        assert content.media_type == "image/png"

def test_fetch_media_file_content_from_local_file_not_found():
    with patch("pathlib.Path.is_file", return_value=False):
        with pytest.raises(RuntimeError, match="does not exist"):
            utils.fetch_media_file_content_from_local("test.png", "/tmp")

def test_fetch_media_file_content_from_local_invalid_mime():
    with patch("pathlib.Path.is_file", return_value=True), \
         patch("mimetypes.guess_type", return_value=("text/plain", None)):
         
         with pytest.raises(RuntimeError, match="not a media file"):
             utils.fetch_media_file_content_from_local("test.txt", "/tmp")

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import runpy
import sys
from unittest.mock import MagicMock, patch


def test_download_fetches_model_snapshot_without_onnx_and_images():
    mock_hub = MagicMock()
    mock_config = MagicMock()
    mock_config.EmbeddingServiceConfig.TEXT_MODEL_NAME = "BAAI/bge-m3"
    mock_config.EmbeddingServiceConfig.TEXT_MODEL_PATH = "models/embedding_model"
    mock_config.EmbeddingServiceConfig.TEXT_MODEL_REVISION = "abc123"
    mock_config.EmbeddingServiceConfig.TEXT_MODEL_DOWNLOAD_IGNORE_PATTERNS = ("onnx/*", "imgs/*")

    with patch.dict(sys.modules, {"huggingface_hub": mock_hub, "config": mock_config}):
        runpy.run_module("scripts.download_embedding_model", run_name="__main__")

    mock_hub.snapshot_download.assert_called_once_with(
        "BAAI/bge-m3", revision="abc123", local_dir="models/embedding_model", ignore_patterns=["onnx/*", "imgs/*"]
    )

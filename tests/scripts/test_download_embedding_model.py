# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import os
import runpy
import sys
from unittest.mock import MagicMock, patch


def _run_script(download_visual: str, visual_model_name: str | None):
    """Runs the download script with FlagEmbedding and sentence_transformers faked."""
    modules = {
        "FlagEmbedding": MagicMock(),
        "sentence_transformers": MagicMock(),
        "config": MagicMock(),
    }
    modules["config"].EmbeddingServiceConfig.TEXT_MODEL_NAME = "BAAI/bge-m3"
    modules["config"].EmbeddingServiceConfig.TEXT_MODEL_PATH = "models/text"
    modules["config"].EmbeddingServiceConfig.VISUAL_MODEL_NAME = visual_model_name
    modules["config"].EmbeddingServiceConfig.VISUAL_MODEL_PATH = "models/visual"

    with (
        patch.dict(sys.modules, modules),
        patch.dict(os.environ, {"EMBEDDING_DOWNLOAD_VISUAL_MODEL": download_visual}),
        patch("os.makedirs") as mock_makedirs,
    ):
        runpy.run_module("scripts.download_embedding_model", run_name="__main__")
    return modules["sentence_transformers"].SentenceTransformer, mock_makedirs


def test_visual_model_downloaded_when_build_arg_enables_it():
    sentence_transformer, mock_makedirs = _run_script(download_visual="true", visual_model_name="BAAI/BGE-VL-base")

    sentence_transformer.assert_called_once_with("BAAI/BGE-VL-base", trust_remote_code=True)
    sentence_transformer.return_value.save.assert_called_once_with("models/visual")
    mock_makedirs.assert_called_with("models/visual", exist_ok=True)


def test_visual_model_skipped_when_build_arg_not_set():
    sentence_transformer, _ = _run_script(download_visual="false", visual_model_name="BAAI/BGE-VL-base")

    sentence_transformer.assert_not_called()


def test_visual_model_skipped_when_visual_model_name_unset():
    sentence_transformer, _ = _run_script(download_visual="true", visual_model_name=None)

    sentence_transformer.assert_not_called()

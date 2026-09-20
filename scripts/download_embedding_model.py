# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""
Downloads the embedding model at image build time (WS6).

Runtime model downloads are disabled by pointing the service at the local copy
under local_models/.
"""

import os
import sys

# Add the parent directory to the path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _download_text_model() -> None:
    from FlagEmbedding import BGEM3FlagModel

    from config import EmbeddingServiceConfig

    model_name = EmbeddingServiceConfig.TEXT_MODEL_NAME
    model_path = EmbeddingServiceConfig.TEXT_MODEL_PATH

    os.makedirs(model_path, exist_ok=True)
    print(f"Downloading embedding model '{model_name}' to '{model_path}'...")
    model = BGEM3FlagModel(model_name, use_fp16=False)
    model.save(model_path)
    print("Embedding model download complete.")


if __name__ == "__main__":
    _download_text_model()

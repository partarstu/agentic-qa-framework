# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Downloads the embedding model at image build time, so the service can run against the local copy under local_models/
instead of downloading at runtime.
"""

import os
import sys

# Add the parent directory to the path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _download_text_model() -> None:
    from huggingface_hub import snapshot_download

    from config import EmbeddingServiceConfig

    model_name = EmbeddingServiceConfig.TEXT_MODEL_NAME
    model_path = EmbeddingServiceConfig.TEXT_MODEL_PATH
    revision = EmbeddingServiceConfig.TEXT_MODEL_REVISION

    print(f"Downloading embedding model '{model_name}@{revision}' to '{model_path}'...")
    snapshot_download(model_name, revision=revision, local_dir=model_path, ignore_patterns=["onnx/*", "imgs/*"])
    print("Embedding model download complete.")


if __name__ == "__main__":
    _download_text_model()

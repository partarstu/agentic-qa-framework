# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Script to download the embedding model for the VectorDbService.

This script downloads the SentenceTransformer embedding model and saves it locally
to avoid downloading it every time the service is initialized.
"""

import os
import sys

# Add the parent directory to the path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import config before sentence_transformers to ensure HF_HOME is set
from config import QdrantConfig  # noqa: I001

from sentence_transformers import SentenceTransformer

if __name__ == "__main__":
    model_name = QdrantConfig.EMBEDDING_MODEL
    model_path = QdrantConfig.EMBEDDING_MODEL_PATH

    if not os.path.exists(model_path):
        os.makedirs(model_path)

    print(f"Downloading embedding model '{model_name}' to '{model_path}'...")

    # Download and save the model
    model = SentenceTransformer(model_name, trust_remote_code=True)
    model.save(model_path)

    print("Embedding model download complete.")

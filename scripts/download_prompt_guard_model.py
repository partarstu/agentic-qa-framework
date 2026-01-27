# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Script to download the prompt injection detection model.

This script downloads the prompt injection detection model and saves it locally
to avoid downloading it every time the service is initialized.
"""

import os
import sys

# Add the parent directory to the path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import config before transformers to ensure HF_HOME is set
from config import (  # noqa: I001
    PROMPT_INJECTION_CHECK_ENABLED,
    PROMPT_INJECTION_DETECTION_MODEL_NAME,
    PROMPT_INJECTION_DETECTION_MODEL_PATH,
)

from transformers import AutoModelForSequenceClassification, AutoTokenizer

if __name__ == "__main__":
    if not PROMPT_INJECTION_CHECK_ENABLED:
        print("Prompt injection detection is disabled, skipping detection model download.")
    else:
        if not os.path.exists(PROMPT_INJECTION_DETECTION_MODEL_PATH):
            os.makedirs(PROMPT_INJECTION_DETECTION_MODEL_PATH)

        print(f"Prompt injection detection is enabled, downloading model {PROMPT_INJECTION_DETECTION_MODEL_NAME} "
              f"to {PROMPT_INJECTION_DETECTION_MODEL_PATH}...")

        # Download and save the tokenizer
        tokenizer = AutoTokenizer.from_pretrained(PROMPT_INJECTION_DETECTION_MODEL_NAME)
        tokenizer.save_pretrained(PROMPT_INJECTION_DETECTION_MODEL_PATH)

        # Download and save the model
        model = AutoModelForSequenceClassification.from_pretrained(PROMPT_INJECTION_DETECTION_MODEL_NAME)
        model.save_pretrained(PROMPT_INJECTION_DETECTION_MODEL_PATH)

        print("Model download complete.")

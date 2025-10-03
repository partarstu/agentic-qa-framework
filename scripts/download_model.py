import os
from transformers import AutoTokenizer, AutoModelForSequenceClassification

from config import PROMPT_INJECTION_CHECK_ENABLED, PROMPT_INJECTION_DETECTION_MODEL_PATH, \
    PROMPT_INJECTION_DETECTION_MODEL_NAME

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

import os
import threading

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

import config
from common import utils

logger = utils.get_logger("prompt_guard_service")

app = FastAPI(title="Prompt Guard Service")

SLIDING_WINDOW_SIZE = 128
MAX_TOKEN_LENGTH = 512
MODEL_PATH = config.PROMPT_INJECTION_DETECTION_MODEL_PATH

class PromptGuardRequest(BaseModel):
    prompt: str
    prompt_description: str | None = ""
    threshold: float

class PromptGuardResponse(BaseModel):
    is_injection: bool

class ProtectAiPromptGuard:
    _instance: 'ProtectAiPromptGuard' = None
    _lock = threading.Lock()

    @staticmethod
    def get_instance() -> 'ProtectAiPromptGuard':
        if not ProtectAiPromptGuard._instance:
            with ProtectAiPromptGuard._lock:
                if not ProtectAiPromptGuard._instance:
                    ProtectAiPromptGuard._instance = ProtectAiPromptGuard()
        return ProtectAiPromptGuard._instance

    def __init__(self):
        logger.info(f"Initializing Prompt Guard model from {MODEL_PATH}")
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
            self.classifier = pipeline(
                "text-classification",
                model=AutoModelForSequenceClassification.from_pretrained(MODEL_PATH),
                tokenizer=self.tokenizer,
                device=torch.device("cuda" if torch.cuda.is_available() else "cpu"),
            )
            logger.info("Prompt Guard model initialized successfully")
        except Exception as e:
            logger.exception("Failed to load model and tokenizer")
            raise RuntimeError(f"Failed to load model and tokenizer: {e!s}")

    def is_injection(self, prompt_text: str, prompt_description: str, threshold: float) -> bool:
        tokens = self.tokenizer.encode(prompt_text)
        chunks = [prompt_text] if len(tokens) <= MAX_TOKEN_LENGTH else self._split_prompt_into_chunks(tokens)

        if prompt_description:
            chunks = [f"{prompt_description}{chunk}" for chunk in chunks]

        results = self.classifier(chunks)

        positive_detections = []
        for chunk, result in zip(chunks, results, strict=False):
            if result.get('label', '').lower() != 'safe' and result.get('score', 0.0) >= threshold:
                positive_detections.append({'result': result, 'chunk': chunk})

        if positive_detections:
            logger.warning("Got positive prompt injection identification results:")
            for detection in positive_detections:
                logger.warning(f"  Result: {detection['result']}, Chunk: '{detection['chunk']}'")
            return True
        return False

    def _split_prompt_into_chunks(self, tokens):
        chunks = []
        for i in range(0, len(tokens), MAX_TOKEN_LENGTH - SLIDING_WINDOW_SIZE):
            chunk = tokens[i:(i + MAX_TOKEN_LENGTH)]
            chunks.append(self.tokenizer.decode(chunk, skip_special_tokens=True))
        if len(chunks) > 1 and chunks[-1] in chunks[-2]:
            chunks.pop()
        return chunks

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/check", response_model=PromptGuardResponse)
async def check_injection(request: PromptGuardRequest):
    try:
        guard = ProtectAiPromptGuard.get_instance()
        is_injection = guard.is_injection(request.prompt, request.prompt_description, request.threshold)
        return PromptGuardResponse(is_injection=is_injection)
    except Exception as e:
        logger.exception("Error checking for prompt injection")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

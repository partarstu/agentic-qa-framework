import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass

import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline

from common import utils

SLIDING_WINDOW_SIZE = 128
MAX_TOKEN_LENGTH = 512
MODEL_NAME = "ProtectAI/deberta-v3-base-prompt-injection-v2"

logger = utils.get_logger("prompt_guard")


@dataclass
class GuardPrompt:
    prompt_description: str
    prompt: str


class PromptGuard(ABC):
    """
    An interface for a prompt guard service.
    """

    @abstractmethod
    def is_injection(self, prompt: GuardPrompt, threshold: float) -> bool:
        """
        Checks if a prompt is a prompt injection attempt.

        Args:
            prompt: The prompt to check.
            threshold: The minimum score for a prompt to be considered an injection.

        Returns:
            True if the prompt is a prompt injection attempt, False otherwise.
        """
        pass


class ProtectAiPromptGuard(PromptGuard):
    """
    A singleton class to detect prompt injection attacks using a pre-trained guard model.
    """
    _instance: 'ProtectAiPromptGuard' = None
    _lock = threading.Lock()
    _allow_init = False

    @staticmethod
    def get_instance() -> 'ProtectAiPromptGuard':
        if not ProtectAiPromptGuard._instance:
            with ProtectAiPromptGuard._lock:
                if not ProtectAiPromptGuard._instance:
                    ProtectAiPromptGuard._allow_init = True
                    ProtectAiPromptGuard._instance = ProtectAiPromptGuard()
                    ProtectAiPromptGuard._allow_init = False
        return ProtectAiPromptGuard._instance

    def __init__(self):
        """
        Initializes the guard by loading the model and tokenizer.
        """
        if not ProtectAiPromptGuard._allow_init:
            raise RuntimeError("Use get_instance() to get the instance of this class.")
        try:
            self._initialized = True
            self.tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
            self.classifier = pipeline(
                "text-classification",
                model=AutoModelForSequenceClassification.from_pretrained(MODEL_NAME),
                tokenizer=self.tokenizer,
                device=torch.device("cuda" if torch.cuda.is_available() else "cpu"),
            )
        except Exception as e:
            raise RuntimeError(f"Failed to load model and tokenizer: {str(e)}")

    def is_injection(self, prompt: GuardPrompt, threshold: float) -> bool:
        """
        Checks if a prompt is a prompt injection attempt.

        Args:
            prompt: The prompt to check.
            threshold: The minimum score for a prompt to be considered an injection.

        Returns:
            True if the prompt is a prompt injection attempt, False otherwise.
        """
        if not isinstance(prompt, GuardPrompt):
            raise TypeError(f"Prompt must be a GuardPrompt, got {type(prompt)}")

        prompt_text = prompt.prompt
        if not isinstance(prompt_text, str):
            raise TypeError(f"Prompt text must be a string, got {type(prompt_text)}")

        tokens = self.tokenizer.encode(prompt_text)
        if len(tokens) <= MAX_TOKEN_LENGTH:
            chunks = [prompt_text]
        else:
            chunks = self._split_prompt_into_chunks(tokens)
        if prompt.prompt_description:
            chunks = [f"{prompt.prompt_description}{chunk}" for chunk in chunks]

        results = self.classifier(chunks)

        positive_detections = []
        for chunk, result in zip(chunks, results):
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


class PromptGuardFactory:
    """
    A factory for creating prompt guard instances.
    """

    @staticmethod
    def get_prompt_guard(provider_name: str) -> PromptGuard:
        """
        Creates a prompt guard instance based on the provider name.

        Args:
            provider_name: The name of the prompt guard provider.

        Returns:
            An instance of a prompt guard.
        """
        if provider_name == "protect_ai":
            return ProtectAiPromptGuard.get_instance()
        else:
            raise ValueError(f"Unknown prompt guard provider: {provider_name}")

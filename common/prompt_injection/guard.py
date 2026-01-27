import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests

from common import utils
from config import PROMPT_GUARD_SERVICE_URL

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
    A client class to detect prompt injection attacks using a remote guard service.
    """
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
        """
        Initializes the guard client.
        """
        pass

    def is_injection(self, prompt: GuardPrompt, threshold: float) -> bool:
        """
        Checks if a prompt is a prompt injection attempt by calling the remote service.

        Args:
            prompt: The prompt to check.
            threshold: The minimum score for a prompt to be considered an injection.

        Returns:
            True if the prompt is a prompt injection attempt, False otherwise.
        """
        if not isinstance(prompt, GuardPrompt):
            raise TypeError(f"Prompt must be a GuardPrompt, got {type(prompt)}")

        if not PROMPT_GUARD_SERVICE_URL:
             raise RuntimeError("PROMPT_GUARD_SERVICE_URL is not set in configuration")

        try:
            payload = {
                "prompt": prompt.prompt,
                "prompt_description": prompt.prompt_description,
                "threshold": threshold
            }
            response = requests.post(f"{PROMPT_GUARD_SERVICE_URL}/check", json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()

            is_injection = result.get("is_injection", False)
            if is_injection:
                logger.warning(f"Remote service detected prompt injection in prompt: {prompt.prompt[:50]}...")

            return is_injection

        except Exception as e:
            logger.exception(f"Error calling prompt guard service: {e}")
            # If the service is unreachable, we might want to block (fail closed) or allow (fail open).
            # Assuming fail-closed for security: treat error as potential injection or just raise.
            raise RuntimeError(f"Failed to check prompt injection: {e}")


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

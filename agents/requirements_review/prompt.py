# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from pathlib import Path

from common import utils
from common.prompt_base import PromptBase

logger = utils.get_logger("reviewer.agent")
PROMPTS_ROOT = "system_prompts"


def _get_prompts_root() -> Path:
    return Path(__file__).resolve().parent.joinpath(PROMPTS_ROOT)


def _load_grounding_suffix() -> str:
    """Loads the grounding instruction appended when document retrieval is enabled.

    Loaded through PromptBase so PROMPT_OVERRIDES_DIR can replace it like any
    other template.
    """
    return _GroundingSuffixPrompt().template


class _GroundingSuffixPrompt(PromptBase):
    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "retrieval_grounding_suffix.md"):
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        return self.template


class RequirementsReviewSystemPrompt(PromptBase):
    """
    Loads a prompt template for main orchestrator instructions.
    """

    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "main_prompt_template.md"):
        """
        Initializes the InstructionPrompt instance.

        Args:
            template_file_name: The name of the prompt template file.
        """
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        """Returns the formatted prompt as a string."""
        logger.info("Generating main requirements reviewer system prompt")
        return self.template


class RequirementsReviewWithAttachmentsPrompt(PromptBase):
    """
    Prompt for the sub-agent that reviews requirements with binary attachments.
    """

    @classmethod
    def grounding_suffix(cls) -> str:
        """Returns the grounding instruction appended when document retrieval is enabled."""
        return _load_grounding_suffix()

    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(
        self,
        template_file_name: str = "review_with_attachments_prompt.md",
        grounding_instruction: str | None = None,
    ):
        """
        Initializes the review with attachments prompt.

        Args:
            template_file_name: The name of the prompt template file.
            grounding_instruction: Optional grounding instruction appended when
                document retrieval is enabled.
        """
        super().__init__(template_file_name)
        self.grounding_instruction = grounding_instruction

    def get_prompt(self) -> str:
        """Returns the prompt as a string."""
        logger.info(
            "Generating system prompt for sub-agent which performs requirements review with all attachments included"
        )
        if self.grounding_instruction:
            return f"{self.template}\n\n{self.grounding_instruction}"
        return self.template


class RequirementsReviewRetrievalInstruction(PromptBase):
    """
    Retrieval instruction appended to the main prompt when document retrieval is enabled (WS10).
    """

    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "retrieval_instruction_template.md"):
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        logger.info("Generating document retrieval instruction prompt")
        return self.template

# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from common import utils
from common.prompt_base import PromptBase

logger = utils.get_logger("reviewer.agent")
PROMPTS_ROOT = "system_prompts"


def _get_prompts_root() -> Path:
    return Path(__file__).resolve().parent.joinpath(PROMPTS_ROOT)


class RequirementsReviewSystemPrompt(PromptBase):
    """
    Loads a prompt template for main orchestrator instructions.
    """

    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, attachments_remote_folder_path: str, template_file_name: str = "main_prompt_template.txt"):
        """
        Initializes the InstructionPrompt instance.

        Args:
            attachments_remote_folder_path: The remote folder path for attachments.
            template_file_name: The name of the prompt template file.
        """
        super().__init__(template_file_name)
        self.attachments_remote_folder_path = attachments_remote_folder_path

    def get_prompt(self) -> str:
        """Returns the formatted prompt as a string."""
        logger.info("Generating main requirements reviewer system prompt")
        return self.template.format(attachments_remote_folder_path=self.attachments_remote_folder_path)


class RequirementsReviewWithAttachmentsPrompt(PromptBase):
    """
    Prompt for the sub-agent that reviews requirements with binary attachments.
    """

    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "review_with_attachments_prompt.txt"):
        """
        Initializes the review with attachments prompt.

        Args:
            template_file_name: The name of the prompt template file.
        """
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        """Returns the prompt as a string."""
        logger.info("Generating system prompt for sub-agent which performs requirements review with all attachments included")
        return self.template

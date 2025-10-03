# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from common.prompt_base import PromptBase
from common import utils

logger = utils.get_logger("reviewer.agent")


class RequirementsReviewSystemPrompt(PromptBase):
    """
    Loads a prompt template for instructions, replaces placeholders with actual values,
    and provides the final prompt as a string.
    """

    def get_script_dir(self) -> Path:
        return Path(__file__).resolve().parent

    def __init__(self, attachments_remote_folder_path: str, template_file_name: str = "prompt_template.txt"):
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
        logger.info("Generating requirements reviewer system prompt")
        return self.template.format(attachments_remote_folder_path=self.attachments_remote_folder_path)

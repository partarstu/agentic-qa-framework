# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from common import utils
from common.prompt_base import PromptBase

logger = utils.get_logger("jira_rag_update_prompt")


class JiraRagUpdateSystemPrompt(PromptBase):
    """System prompt for the JiraRagUpdateAgent."""

    def get_script_dir(self) -> Path:
        return Path(__file__).resolve().parent

    def __init__(
        self,
        valid_statuses: list[str],
        template_file_name: str = "prompt_template.txt",
    ):
        """
        Initializes the JiraRagUpdateSystemPrompt instance.

        Args:
            valid_statuses: List of valid issue statuses for the RAG DB.
            template_file_name: The name of the prompt template file.
        """
        super().__init__(template_file_name)
        self.valid_statuses = valid_statuses

    def get_prompt(self) -> str:
        """Returns the formatted prompt string with substituted values."""
        logger.info("Generating Jira RAG update system prompt")
        return self.template.format(
            valid_statuses=self.valid_statuses
        )

# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
from common.prompt_base import PromptBase
from common import utils

logger = utils.get_logger("jira_rag_update_prompt")


class JiraRagUpdateSystemPrompt(PromptBase):
    """System prompt for the JiraRagUpdateAgent."""

    def get_script_dir(self) -> Path:
        return Path(__file__).resolve().parent

    def __init__(
        self,
        valid_statuses: list[str],
        bug_issue_type: str,
        template_file_name: str = "prompt_template.txt",
    ):
        """
        Initializes the JiraRagUpdateSystemPrompt instance.

        Args:
            valid_statuses: List of valid issue statuses for the RAG DB.
            bug_issue_type: The issue type to filter for (e.g., 'Bug').
            template_file_name: The name of the prompt template file.
        """
        super().__init__(template_file_name)
        self.valid_statuses = valid_statuses
        self.bug_issue_type = bug_issue_type

    def get_prompt(self) -> str:
        """Returns the formatted prompt string with substituted values."""
        logger.info("Generating Jira RAG update system prompt")
        return self.template.format(
            valid_statuses=self.valid_statuses,
            bug_issue_type=self.bug_issue_type,
        )

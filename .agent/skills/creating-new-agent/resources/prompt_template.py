# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Prompt class template for a new agent.

Replace <agent_name> with your agent's folder name (e.g., requirements_review).
Replace <AgentName> with your agent's class name (e.g., RequirementsReview).
"""

from pathlib import Path

from common import utils
from common.prompt_base import PromptBase

logger = utils.get_logger("<agent_name>.agent")
PROMPTS_ROOT = "system_prompts"


def _get_prompts_root() -> Path:
    return Path(__file__).resolve().parent.joinpath(PROMPTS_ROOT)


class <AgentName>SystemPrompt(PromptBase):
    """
    Loads the main system prompt template for <Agent Name>.
    """

    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(
        self,
        # Add any template variables as constructor parameters
        template_file_name: str = "main_prompt_template.txt"
    ):
        """
        Initializes the prompt instance.

        Args:
            template_file_name: The name of the prompt template file.
        """
        super().__init__(template_file_name)
        # Store template variables for formatting

    def get_prompt(self) -> str:
        """Returns the formatted prompt as a string."""
        logger.info("Generating <agent_name> system prompt")
        # Return template with variables substituted
        return self.template.format(
            # variable_name=self.variable_name
        )

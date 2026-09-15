# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""
Prompt class template for a new agent.

Replace <agent_name> with the folder name (e.g. requirements_review) and <AgentName> with the class prefix
(e.g. RequirementsReview).
"""

from pathlib import Path

from common import utils
from common.prompt_base import PromptBase

logger = utils.get_logger("<agent_name>_agent")
PROMPTS_ROOT = "system_prompts"


def _get_prompts_root() -> Path:
    return Path(__file__).resolve().parent.joinpath(PROMPTS_ROOT)


class <AgentName>SystemPrompt(PromptBase):
    """Loads the main system prompt template of the <Agent Name> agent."""

    def __init__(self, template_file_name: str = "main_prompt_template.txt"):
        super().__init__(template_file_name)

    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def get_prompt(self) -> str:
        """Returns the system prompt.

        If the template has placeholders, return `self.template.format(...)` instead and escape
        literal braces in the template as `{{` and `}}`.
        """
        logger.info("Generating <agent_name> system prompt")
        return self.template

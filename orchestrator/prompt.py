# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""System prompt templates used by the orchestrator's internal LLM agents."""

from pathlib import Path

import config
from common import utils
from common.prompt_base import PromptBase

logger = utils.get_logger("orchestrator.prompts")

PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


class OrchestratorPrompt(PromptBase):
    """Loads one orchestrator instruction template."""

    def get_script_dir(self) -> Path:
        return PROMPTS_ROOT

    def __init__(self, template_file_name: str):
        """
        Initializes the OrchestratorPrompt instance.

        Args:
            template_file_name: The name of the prompt template file.
        """
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        """Returns the formatted prompt as a string."""
        return self.template


def _load_instruction(template_file_name: str) -> str:
    return OrchestratorPrompt(template_file_name).get_prompt()


ROUTING_INSTRUCTION = _load_instruction("routing_instruction_template.md")
MULTI_ROUTING_INSTRUCTION = _load_instruction("multi_routing_instruction_template.md")
RESULTS_EXTRACTOR_INSTRUCTION = _load_instruction("results_extractor_instruction_template.md")
ADDITIONAL_FIELDS_INSTRUCTION_TEMPLATE = OrchestratorPrompt("additional_fields_instruction_template.md")


def build_additional_fields_instruction() -> str:
    """Renders the additional Jira fields instruction, or an empty string when none are configured.

    The template is loaded through PromptBase, so PROMPT_OVERRIDES_DIR overrides this instruction
    too. Rendering happens at call time over the already-validated JIRA_ADDITIONAL_FIELD_IDS.
    """
    if not config.JIRA_ADDITIONAL_FIELD_IDS:
        return ""
    return ADDITIONAL_FIELDS_INSTRUCTION_TEMPLATE.template.format(
        additional_field_ids=", ".join(config.JIRA_ADDITIONAL_FIELD_IDS)
    )

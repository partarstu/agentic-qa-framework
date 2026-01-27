# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

import config
from common import utils
from common.prompt_base import PromptBase

logger = utils.get_logger("incident_creation_agent")


def _get_prompts_root() -> Path:
    return Path(__file__).resolve().parent


def _format_values_for_prompt(values_string: str) -> str:
    """Formats a comma-separated 'value:description' string into prompt-friendly format.

    Args:
        values_string: Comma-separated string of "value:description" pairs.

    Returns:
        Formatted string like "`Value1` (description1), `Value2` (description2)".
    """
    pairs = values_string.split(",")
    formatted_pairs = []
    for pair in pairs:
        pair = pair.strip()
        if ":" in pair:
            value, description = pair.split(":", 1)
            formatted_pairs.append(f"`{value.strip()}` ({description.strip()})")
        else:
            formatted_pairs.append(f"`{pair}`")
    return ", ".join(formatted_pairs)


class IncidentCreationPrompt(PromptBase):
    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "prompt_template.txt"):
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        logger.info("Generating incident creation system prompt")
        severity_values = _format_values_for_prompt(
            config.IncidentCreationAgentConfig.SEVERITY_VALUES
        )
        priority_values = _format_values_for_prompt(
            config.IncidentCreationAgentConfig.PRIORITY_VALUES
        )
        return self.template.format(
            SEVERITY_VALUES=severity_values,
            PRIORITY_VALUES=priority_values
        )

class DuplicateDetectionPrompt(PromptBase):
    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "duplicate_detection_prompt_template.txt"):
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        logger.info("Generating duplicate detection system prompt")
        return self.template

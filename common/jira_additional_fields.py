# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""The instruction that makes an agent fetch the configured additional Jira custom fields with the issue."""

from pathlib import Path

import config
from common.prompt_base import PromptBase


class AdditionalFieldsInstructionPrompt(PromptBase):
    """The instruction template, kept in the top-level prompts folder so an existing override keeps its path."""

    def get_script_dir(self) -> Path:
        return Path(__file__).resolve().parent.parent / "prompts"

    def get_prompt(self) -> str:
        return self.template


ADDITIONAL_FIELDS_INSTRUCTION_TEMPLATE = AdditionalFieldsInstructionPrompt("additional_fields_instruction_template.md")


def build_additional_fields_instruction() -> str:
    """Renders the additional Jira fields instruction at call time, or an empty string when none are configured."""
    if not config.JIRA_ADDITIONAL_FIELD_IDS:
        return ""
    return ADDITIONAL_FIELDS_INSTRUCTION_TEMPLATE.template.format(
        additional_field_ids=", ".join(config.JIRA_ADDITIONAL_FIELD_IDS)
    )

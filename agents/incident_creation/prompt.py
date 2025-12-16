# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
from common.prompt_base import PromptBase
from common import utils

logger = utils.get_logger("incident_creation_agent")

def _get_prompts_root() -> Path:
    return Path(__file__).resolve().parent

class IncidentCreationPrompt(PromptBase):
    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "prompt_template.txt"):
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        logger.info("Generating incident creation system prompt")
        return self.template

class DuplicateDetectionPrompt(PromptBase):
    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "duplicate_detection_prompt_template.txt"):
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        logger.info("Generating duplicate detection system prompt")
        return self.template

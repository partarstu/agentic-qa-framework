# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from common import utils
from common.prompt_base import PromptBase

logger = utils.get_logger("test_case_generation_agent")
PROMPTS_ROOT = "system_prompts"

def _get_prompts_root() -> Path:
    return Path(__file__).resolve().parent.joinpath(PROMPTS_ROOT)


class TestCaseGenerationSystemPrompt(PromptBase):
    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, attachments_remote_folder_path: str, template_file_name: str = "main_prompt_template.txt"):
        super().__init__(template_file_name)
        self.attachments_remote_folder_path = attachments_remote_folder_path

    def get_prompt(self) -> str:
        logger.info("Generating test case generation main system prompt")
        return self.template.format(attachments_remote_folder_path=self.attachments_remote_folder_path)


class AcExtractionPrompt(PromptBase):
    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "ac_extraction_prompt.txt"):
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        return self.template


class StepsGenerationPrompt(PromptBase):
    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "steps_generation_prompt.txt"):
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        return self.template


class TestCaseCreationPrompt(PromptBase):
    def get_script_dir(self) -> Path:
        return _get_prompts_root()

    def __init__(self, template_file_name: str = "test_case_creation_prompt.txt"):
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        return self.template

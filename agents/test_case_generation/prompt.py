# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
from agents.prompt_base import PromptBase
from common import utils

logger = utils.get_logger("test_case_generation_agent")


class TestCaseGenerationSystemPrompt(PromptBase):
    def get_script_dir(self) -> Path:
        return Path(__file__).resolve().parent

    def __init__(self, attachments_remote_folder_path: str, template_file_name: str = "prompt_template.txt"):
        super().__init__(template_file_name)
        self.attachments_remote_folder_path = attachments_remote_folder_path

    def get_prompt(self) -> str:
        logger.info("Generating test case generation system prompt")
        return self.template.format(attachments_remote_folder_path=self.attachments_remote_folder_path)

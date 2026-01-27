# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from common import utils
from common.prompt_base import PromptBase

logger = utils.get_logger("test_case_classification_prompt")


class TestCaseClassificationSystemPrompt(PromptBase):
    def get_script_dir(self) -> Path:
        return Path(__file__).resolve().parent

    def __init__(self, template_file_name: str = "prompt_template.txt"):
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        logger.info("Generating test case classification system prompt")
        return self.template

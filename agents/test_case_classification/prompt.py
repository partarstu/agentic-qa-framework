# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from pathlib import Path

from common import utils
from common.models import TestCaseType
from common.prompt_base import PromptBase

logger = utils.get_logger("test_case_classification_prompt")


class TestCaseClassificationSystemPrompt(PromptBase):
    def get_script_dir(self) -> Path:
        return Path(__file__).resolve().parent

    def __init__(self, template_file_name: str = "prompt_template.md"):
        super().__init__(template_file_name)

    def get_prompt(self) -> str:
        """Returns the prompt with the test types rendered from the TestCaseType enumeration (WS15)."""
        logger.info("Generating test case classification system prompt")
        test_types = "\n".join(f"- `{test_type.value}`: label `{test_type.label}`" for test_type in TestCaseType)
        return self.template.format(test_types=test_types)

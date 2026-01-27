
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

from common.prompt_base import PromptBase


class MockPrompt(PromptBase):
    def get_prompt(self) -> str:
        return self.template

    def get_script_dir(self) -> Path:
        return Path("/tmp")

def test_prompt_base_success():
    with patch("pathlib.Path.is_file", return_value=True), \
         patch("pathlib.Path.read_text", return_value="template content"):

        prompt = MockPrompt("template.txt")
        assert prompt.template == "template content"
        assert prompt.get_prompt() == "template content"

def test_prompt_base_file_not_found():
    with patch("pathlib.Path.is_file", return_value=False), pytest.raises(FileNotFoundError):
        MockPrompt("template.txt")

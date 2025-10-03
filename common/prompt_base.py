# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import os
from abc import ABC, abstractmethod
from pathlib import Path


class PromptBase(ABC):
    """
    Abstract base class for prompts.
    """

    def __init__(self, template_file_name: str):
        """
        Initializes the PromptBase instance.

        Args:
            template_file_name: The name of the prompt template file.
        """
        self.template_path = Path(os.path.join(self.get_script_dir(), template_file_name)).resolve()
        if not self.template_path.is_file():
            raise FileNotFoundError(f"Error: The prompt template file was not found at the specified "
                                    f"path: {self.template_path}")
        self.template = self._load_template()

    def _load_template(self) -> str:
        """Loads the prompt template from the file."""
        return self.template_path.read_text()

    @abstractmethod
    def get_prompt(self) -> str:
        """Returns the formatted prompt string."""
        raise NotImplementedError("This method must be implemented by subclasses.")

    @abstractmethod
    def get_script_dir(self) -> Path:
        """Returns the formatted prompt string."""
        raise NotImplementedError("This method must be implemented by subclasses.")

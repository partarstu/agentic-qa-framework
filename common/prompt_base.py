# SPDX-FileCopyrightText: 2025-2026 Taras Paruka (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import re
from abc import ABC, abstractmethod
from pathlib import Path

import config
from common import utils

logger = utils.get_logger("prompt_base")

_PLACEHOLDER_PATTERN = re.compile(r"{([a-zA-Z_][a-zA-Z0-9_]*)}")


def _repo_root() -> Path:
    """Repository root: the directory that holds the top-level packages."""
    return Path(__file__).resolve().parent.parent


def _extract_placeholders(template: str) -> set[str]:
    """Named placeholders of a template, ignoring escaped ``{{``/``}}`` literal braces."""
    return set(_PLACEHOLDER_PATTERN.findall(template))


class PromptBase(ABC):
    """
    Abstract base class for prompts.

    Bundled templates live under the package returned by :meth:`get_script_dir`. When
    ``PROMPT_OVERRIDES_DIR`` is set, a file at the same repository-relative path inside that
    directory replaces the bundled one; overrides load once at process start (no hot reload).
    """

    def __init__(self, template_file_name: str):
        """
        Initializes the PromptBase instance.

        Args:
            template_file_name: The name of the prompt template file.

        Raises:
            FileNotFoundError: If neither a bundled template nor an override exists.
            NotADirectoryError: If the configured override directory is missing.
            ValueError: If an override's placeholders differ from the bundled template's.
        """
        bundled_path = (Path(self.get_script_dir()) / template_file_name).resolve()
        override_path = self._resolve_override(bundled_path)
        self.template_path = override_path or bundled_path
        if not self.template_path.is_file():
            raise FileNotFoundError(
                f"Error: The prompt template file was not found at the specified path: {self.template_path}"
            )
        self.template = self._load_template(bundled_path)

    def _resolve_override(self, bundled_path: Path) -> Path | None:
        """Resolve the override path for one bundled template, with startup validation.

        Returns:
            The override path when an override exists, otherwise None.

        Raises:
            NotADirectoryError: If the override directory is set but missing or not a directory.
            ValueError: If the resolved override path escapes the override directory.
        """
        overrides_dir = config.PROMPT_OVERRIDES_DIR
        if not overrides_dir:
            return None
        override_root = Path(overrides_dir).resolve()
        if not override_root.is_dir():
            raise NotADirectoryError(
                f"PROMPT_OVERRIDES_DIR is set to '{overrides_dir}' which is missing or not a directory."
            )
        relative = bundled_path.relative_to(_repo_root())
        override_path = (override_root / relative).resolve()
        if not override_path.is_file():
            return None
        if not override_path.is_relative_to(override_root):
            raise ValueError(f"Resolved override path '{override_path}' escapes '{override_root}'.")
        logger.info(f"Using prompt override '{override_path}' instead of '{bundled_path}'.")
        return override_path

    def _load_template(self, bundled_path: Path) -> str:
        """Loads the prompt template from the file, explicitly as UTF-8.

        An override is validated against the bundled template's named placeholders so a
        mismatch fails at startup instead of at the first task.
        """
        template = self.template_path.read_text(encoding="utf-8")
        if self.template_path != bundled_path and bundled_path.is_file():
            self._validate_override_placeholders(template, bundled_path.read_text(encoding="utf-8"))
        return template

    def _validate_override_placeholders(self, override_template: str, bundled_template: str) -> None:
        """Fail fast when an override's named placeholders differ from the bundled template's."""
        missing = _extract_placeholders(bundled_template) - _extract_placeholders(override_template)
        unknown = _extract_placeholders(override_template) - _extract_placeholders(bundled_template)
        if missing or unknown:
            details = []
            if missing:
                details.append(f"missing: {sorted(missing)}")
            if unknown:
                details.append(f"unknown: {sorted(unknown)}")
            raise ValueError(
                f"Prompt override '{self.template_path}' has placeholders that differ from the bundled "
                f"template ({'; '.join(details)})."
            )

    @abstractmethod
    def get_prompt(self) -> str:
        """Returns the formatted prompt string."""
        raise NotImplementedError("This method must be implemented by subclasses.")

    @abstractmethod
    def get_script_dir(self) -> Path:
        """Returns the directory holding the bundled prompt templates."""
        raise NotImplementedError("This method must be implemented by subclasses.")

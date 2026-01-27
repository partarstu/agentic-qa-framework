# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Utility module for handling Jira attachments for agent processing.

Provides functionality to fetch, filter, and convert attachments to BinaryContent
for multimodal processing by Pydantic AI agents.
"""

import mimetypes
from pathlib import Path
from typing import get_args

try:
    import magic
except ImportError:
    import warnings
    warnings.warn("python-magic not available, MIME detection will rely on file extensions only.", stacklevel=2)
    magic = None
from pydantic_ai.messages import (
    AudioMediaType,
    BinaryContent,
    DocumentMediaType,
    ImageMediaType,
    VideoMediaType,
)

import config
from common import utils

logger = utils.get_logger("attachment_handler")

# Collect all MIME types that Pydantic AI supports in its type annotations
PYDANTIC_SUPPORTED_IMAGE_TYPES: set[str] = set(get_args(ImageMediaType))
PYDANTIC_SUPPORTED_AUDIO_TYPES: set[str] = set(get_args(AudioMediaType))
PYDANTIC_SUPPORTED_VIDEO_TYPES: set[str] = set(get_args(VideoMediaType))
PYDANTIC_SUPPORTED_DOCUMENT_TYPES: set[str] = set(get_args(DocumentMediaType))

PYDANTIC_SUPPORTED_MIME_TYPES: set[str] = (
        PYDANTIC_SUPPORTED_IMAGE_TYPES
        | PYDANTIC_SUPPORTED_AUDIO_TYPES
        | PYDANTIC_SUPPORTED_VIDEO_TYPES
        | PYDANTIC_SUPPORTED_DOCUMENT_TYPES
)

# Final supported MIME types: intersection of config-defined types and Pydantic AI types
# This ensures we only allow types that are both:
#   1. Supported by the actual model API (defined in config)
#   2. Supported by Pydantic AI's type system
SUPPORTED_MIME_TYPES: set[str] = config.SUPPORTED_ATTACHMENT_MIME_TYPES & PYDANTIC_SUPPORTED_MIME_TYPES


def get_mime_type(file_path: str) -> str | None:
    """
    Determine the MIME type of file.

    First attempts to guess from the file extension using mimetypes.
    If that fails, uses python-magic to detect the MIME type from file content.

    Args:
        file_path: Path to the file (used for extension-based detection and magic).
    Returns:
        The detected MIME type string, or None if detection fails.
    """
    # Try extension-based detection first
    mime_type, _ = mimetypes.guess_file_type(file_path)
    if mime_type:
        return mime_type

    # Fall back to content-based detection
    if magic:
        try:
            return magic.from_file(file_path, mime=True)
        except Exception as e:
            logger.warning("Failed to detect MIME type using magic for %s: %s", file_path, e)
    else:
        logger.warning("python-magic not available, skipping content-based MIME detection for %s", file_path)
    return None


def should_skip_attachment(filename: str, skip_postfix: str | None = None) -> bool:
    """
    Check if an attachment should be skipped based on its filename.

    The check is case-insensitive for better user experience.

    Args:
        filename: The name of the attachment file.
        skip_postfix: The postfix that indicates the file should be skipped.
                     Defaults to config.JIRA_ATTACHMENT_SKIP_POSTFIX.

    Returns:
        True if the attachment should be skipped, False otherwise.
    """
    if skip_postfix is None:
        skip_postfix = config.JIRA_ATTACHMENT_SKIP_POSTFIX

    if not skip_postfix:
        return False

    # Get the file stem (name without extension)
    file_stem = Path(filename).stem
    return file_stem.lower().endswith(skip_postfix.lower())


def is_supported_mime_type(mime_type: str | None) -> bool:
    """
    Check if a MIME type is supported by Pydantic AI for multimodal processing.

    Args:
        mime_type: The MIME type to check.

    Returns:
        True if the MIME type is supported, False otherwise.
    """
    if not mime_type:
        return False
    return mime_type in SUPPORTED_MIME_TYPES


def _fetch_file_bytes(file_path: str) -> tuple[bytes, str]:
    """
    Fetch file bytes from local storage.

    In cloud deployments, GCS buckets are mounted as local folders via Cloud Run
    volume mounts, so all file access is done through the local file system.

    Args:
        file_path: The path to the file (relative path as returned by MCP server).

    Returns:
        Tuple of (file_bytes, filename).

    Raises:
        RuntimeError: If the file cannot be found or read.
    """
    file_name = Path(file_path).name
    local_file_path = Path(config.ATTACHMENTS_LOCAL_DESTINATION_FOLDER_PATH) / file_name
    local_file_path = local_file_path.resolve()

    if not local_file_path.is_file():
        raise RuntimeError(f"File {local_file_path} does not exist.")

    file_bytes = local_file_path.read_bytes()

    return file_bytes, file_name


def fetch_all_attachments(attachment_paths: list[str], skip_postfix: str | None = None) -> dict[str, BinaryContent]:
    """
    Fetch and filter all valid attachments, returning them as a dictionary.

    This method:
    1. Skips files with the configured skip postfix
    2. Fetches file bytes from local storage or GCS
    3. Detects MIME types (using extension or content-based detection)
    4. Filters out unsupported MIME types (including types like .docx, .xlsx that
       Pydantic AI includes but Gemini API doesn't actually support)
    5. Returns a dictionary mapping filenames to BinaryContent objects

    Args:
        attachment_paths: List of file paths to process (as returned by MCP server).
        skip_postfix: Optional override for the skip postfix.
                     Defaults to config.JIRA_ATTACHMENT_SKIP_POSTFIX.

    Returns:
        Dictionary mapping filename to BinaryContent for valid, supported attachments.
    """
    if not attachment_paths:
        return {}

    if skip_postfix is None:
        skip_postfix = config.JIRA_ATTACHMENT_SKIP_POSTFIX

    attachments: dict[str, BinaryContent] = {}
    skipped_count = 0
    unsupported_count = 0
    error_count = 0

    for file_path in attachment_paths:
        filename = Path(file_path).name
        if should_skip_attachment(filename, skip_postfix):
            logger.info("Skipping attachment '%s' due to skip postfix '%s'", filename, skip_postfix)
            skipped_count += 1
            continue

        try:
            file_bytes, _ = _fetch_file_bytes(file_path)
        except Exception as e:
            logger.warning("Failed to fetch attachment '%s': %s", filename, e)
            error_count += 1
            continue

        # Detect MIME type
        mime_type = get_mime_type(file_path)

        # Check if MIME type is supported
        if not is_supported_mime_type(mime_type):
            logger.info("Skipping attachment '%s' - unsupported MIME type: %s", filename, mime_type or "unknown")
            unsupported_count += 1
            continue

        # Create BinaryContent with identifier for reference
        binary_content = BinaryContent(data=file_bytes, media_type=mime_type, identifier=filename)
        attachments[filename] = binary_content
        logger.debug("Added attachment '%s' with MIME type '%s'", filename, mime_type)

    logger.info("Processed %d attachments: %d valid, %d skipped (postfix), %d unsupported, %d errors",
                len(attachment_paths),
                len(attachments),
                skipped_count,
                unsupported_count,
                error_count)
    return attachments

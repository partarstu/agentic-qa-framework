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
import magic
from pydantic_ai.messages import (
    BinaryContent,
    ImageMediaType,
    AudioMediaType,
    VideoMediaType,
    DocumentMediaType,
)

import config
from common import utils

logger = utils.get_logger("attachment_handler")

# Collect all supported MIME types from Pydantic AI type annotations
SUPPORTED_IMAGE_TYPES: set[str] = set(get_args(ImageMediaType))
SUPPORTED_AUDIO_TYPES: set[str] = set(get_args(AudioMediaType))
SUPPORTED_VIDEO_TYPES: set[str] = set(get_args(VideoMediaType))
SUPPORTED_DOCUMENT_TYPES: set[str] = set(get_args(DocumentMediaType))

SUPPORTED_MIME_TYPES: set[str] = (
        SUPPORTED_IMAGE_TYPES
        | SUPPORTED_AUDIO_TYPES
        | SUPPORTED_VIDEO_TYPES
        | SUPPORTED_DOCUMENT_TYPES
)


def get_mime_type(file_path: str, file_bytes: bytes | None = None) -> str | None:
    """
    Determine the MIME type of file.

    First attempts to guess from the file extension using mimetypes.
    If that fails and file_bytes are provided, uses python-magic to detect
    the MIME type from file content.

    Args:
        file_path: Path to the file (used for extension-based detection).
        file_bytes: Optional raw bytes of the file for content-based detection.

    Returns:
        The detected MIME type string, or None if detection fails.
    """
    # Try extension-based detection first
    mime_type, _ = mimetypes.guess_file_type(file_path)
    if mime_type:
        return mime_type

    # Fall back to content-based detection if bytes are provided
    try:
        return magic.from_file(file_path, mime=True)
    except Exception as e:
        logger.warning("Failed to detect MIME type using magic for %s: %s", file_path, e)
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
    local_file_path = Path(config.ATTACHMENTS_DESTINATION_FOLDER_PATH) / file_name
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
    4. Filters out unsupported MIME types
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
        mime_type = get_mime_type(file_path, file_bytes)

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

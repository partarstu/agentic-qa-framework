# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""
Utility module for handling Jira attachments for agent processing.

Provides functionality to resolve and filter the attachments a tool has already returned, as
BinaryContent for multimodal processing by Pydantic AI agents.
"""

from pathlib import Path
from typing import get_args

from pydantic_ai.messages import (
    AudioMediaType,
    BinaryContent,
    DocumentMediaType,
    ImageMediaType,
    ModelMessage,
    ToolReturnPart,
    UserPromptPart,
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

# Types Pydantic AI has no document type for, although the models read them as plain text. Without
# this, a Jira attachment such as a JSON request payload would be dropped as unsupported.
TEXT_EQUIVALENT_MIME_TYPES: dict[str, str] = {"application/json": "text/plain"}


def as_text_equivalent(content: BinaryContent) -> BinaryContent:
    """Return the attachment under a text media type when its own one is only readable as text."""
    text_media_type = TEXT_EQUIVALENT_MIME_TYPES.get(content.media_type)
    if text_media_type is None:
        return content
    return BinaryContent(data=content.data, media_type=text_media_type, identifier=content.identifier)


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


def _iter_binary_contents(messages: list[ModelMessage]):
    """Yield every attachment a tool has already returned or a user message already carries."""
    for message in messages:
        for part in message.parts:
            if isinstance(part, ToolReturnPart):
                yield from (file for file in part.files if isinstance(file, BinaryContent))
            elif isinstance(part, UserPromptPart) and not isinstance(part.content, str):
                yield from (item for item in part.content if isinstance(item, BinaryContent))


def resolve_attachments(messages: list[ModelMessage], skip_postfix: str | None = None) -> dict[str, BinaryContent]:
    """Collect the attachments already downloaded in this run, as binary content for the model.

    The Jira MCP server returns attachments as embedded resources rather than writing them to a
    filesystem, so pydantic-ai already carries them through the run and nothing is read from disk.
    Everything downloaded is taken: which identifiers a model can actually see depends on how its
    provider maps files in a tool result, so letting it name a subset loses attachments silently.

    Args:
        messages: The messages of the current run, as carried by the tool's run context.
        skip_postfix: Optional override for the skip postfix.
                     Defaults to config.JIRA_ATTACHMENT_SKIP_POSTFIX.

    Returns:
        Dictionary mapping identifier to BinaryContent for every supported attachment in the run.
    """
    if skip_postfix is None:
        skip_postfix = config.JIRA_ATTACHMENT_SKIP_POSTFIX

    attachments: dict[str, BinaryContent] = {}
    skipped_count = 0
    unsupported_count = 0

    for downloaded in _iter_binary_contents(messages):
        identifier = downloaded.identifier
        # Only meaningful when the identifier is a file name; MCP-provided ones are opaque.
        if should_skip_attachment(identifier, skip_postfix):
            logger.info("Skipping attachment '%s' due to skip postfix '%s'", identifier, skip_postfix)
            skipped_count += 1
            continue

        content = as_text_equivalent(downloaded)
        if not is_supported_mime_type(content.media_type):
            logger.info("Skipping attachment '%s' - unsupported MIME type: %s", identifier, content.media_type)
            unsupported_count += 1
            continue

        attachments[identifier] = content
        logger.debug("Resolved attachment '%s' with MIME type '%s'", identifier, content.media_type)

    logger.info(
        "Resolved %d attachments: %d valid, %d skipped (postfix), %d unsupported",
        len(attachments) + skipped_count + unsupported_count,
        len(attachments),
        skipped_count,
        unsupported_count,
    )
    return attachments

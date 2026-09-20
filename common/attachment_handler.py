# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Predicates and helpers for the Jira attachments handed to a model as BinaryContent: which files to skip, which MIME
types the models support, and the media-type mapping for text-readable files.
"""

from pathlib import Path
from typing import get_args

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
    """Whether the attachment's file stem ends with the configured skip postfix, ignoring case."""
    if skip_postfix is None:
        skip_postfix = config.JIRA_ATTACHMENT_SKIP_POSTFIX

    if not skip_postfix:
        return False

    file_stem = Path(filename).stem
    return file_stem.lower().endswith(skip_postfix.lower())


def is_supported_mime_type(mime_type: str | None) -> bool:
    """Whether pydantic-ai supports the MIME type for multimodal processing."""
    if not mime_type:
        return False
    return mime_type in SUPPORTED_MIME_TYPES

# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

import base64
import logging
import mimetypes
import os
import sys
from datetime import datetime
from pathlib import Path

from a2a.types import FileWithBytes
from dateutil import parser
from pydantic_ai import BinaryContent

import config

logging_initialized = False


def _initialize_logging():
    global logging_initialized
    if config.GOOGLE_CLOUD_LOGGING_ENABLED:
        import google.cloud.logging
        client = google.cloud.logging.Client()
        client.setup_logging()
    else:
        logging.basicConfig(stream=sys.stdout, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logging_initialized = True


def get_logger(name):
    if not logging_initialized:
        _initialize_logging()
    log_level = config.LOG_LEVEL
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    return logger


def fetch_media_file_content_from_local(remote_file_path: str, attachments_folder_path: str) -> BinaryContent:
    file_name = Path(remote_file_path).name
    local_file_path = Path(os.path.join(attachments_folder_path, file_name)).resolve()
    if not local_file_path.is_file():
        raise RuntimeError(f"File {local_file_path} does not exist.")
    mime_type, _ = mimetypes.guess_type(local_file_path)
    if mime_type and mime_type.startswith(("audio", "video", "image")):
        return BinaryContent(
            data=Path(local_file_path).read_bytes(),
            media_type=mime_type or "application/octet-stream",
        )
    else:
        raise RuntimeError(f"File {local_file_path} is not a media file or mime type could not be determined.")


def get_execution_logs_from_artifacts(artifacts: list[FileWithBytes], log_filename_pattern: str = "logs") -> list[str]:
    if not artifacts:
        return []

    logs = []
    for artifact in artifacts:
        if artifact.name and (log_filename_pattern.lower() in artifact.name.lower()) and (
                artifact.name.endswith(".txt") or artifact.name.endswith(".log")) and artifact.bytes:
            try:
                logs.append(base64.b64decode(artifact.bytes).decode('utf-8'))
            except (UnicodeDecodeError, ValueError) as e:
                get_logger(__name__).warning(f"Failed to decode logs from artifact '{artifact.name}': {e}")
                continue

    return logs


def parse_timestamp(timestamp_str: str | None, field_name: str = "timestamp") -> datetime | None:
    """Parse a timestamp string after removing comma-delimited trailing content."""
    if not timestamp_str:
        return None

    cleaned_timestamp = timestamp_str.split(",", 1)[0].strip()
    if cleaned_timestamp != timestamp_str.strip():
        get_logger(__name__).warning(
            f"Timestamp value for '{field_name}' contained trailing content and was cleaned. "
            f"Original value: '{timestamp_str}'. Cleaned value: '{cleaned_timestamp}'."
        )

    if not cleaned_timestamp:
        get_logger(__name__).warning(f"Ignoring empty timestamp value for '{field_name}'.")
        return None

    try:
        return parser.parse(cleaned_timestamp)
    except (OverflowError, TypeError, ValueError) as e:
        get_logger(__name__).warning(
            f"Ignoring invalid timestamp value for '{field_name}': '{timestamp_str}'. Error: {e}"
        )
        return None

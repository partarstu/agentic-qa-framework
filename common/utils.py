# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import json
import logging
import mimetypes
import os
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

from dateutil import parser
from pydantic_ai import BinaryContent

import config
from common.models import FileArtifact

logging_initialized = False
log_context: ContextVar[dict[str, str | None] | None] = ContextVar("log_context", default=None)

# Length cap for user-supplied name patterns, shared by all call sites.
MAX_NAME_PATTERN_LENGTH = 200


def compile_name_pattern(pattern: str) -> re.Pattern:
    """Compile a user-supplied attachment/document name pattern.

    Patterns are case-insensitive and matched as an unanchored search, so a plain
    pattern like ``report`` behaves like the old substring match. An invalid or
    over-long pattern raises a clear error; patterns only ever run against short
    name strings.
    """
    if len(pattern) > MAX_NAME_PATTERN_LENGTH:
        raise ValueError(f"Name pattern exceeds the {MAX_NAME_PATTERN_LENGTH}-character limit.")
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        raise ValueError(f"Invalid name pattern '{pattern}': {e}") from e


class StructuredLogFilter(logging.Filter):
    """Add execution context to every record without changing call sites."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in (log_context.get() or {}).items():
            if value is not None and not hasattr(record, key):
                setattr(record, key, value)
        return True


class StructuredJsonFormatter(logging.Formatter):
    """Render a log record as one UTC JSON object suitable for Cloud Logging."""

    _CANONICAL_FIELDS = frozenset(
        {"timestamp", "level", "severity", "message", "logger", "module", "line", "agent_name", "task_id", "agent_id"}
    )

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        standard = logging.makeLogRecord({}).__dict__
        custom = {key: value for key, value in record.__dict__.items() if key not in standard and key not in self._CANONICAL_FIELDS}
        payload: dict[str, object] = {"custom": custom} if custom else {}
        payload.update(
            {
                "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
                "level": record.levelname,
                "severity": record.levelname,
                "message": message,
                "logger": record.name,
                "module": record.module,
                "line": record.lineno,
                "agent_name": getattr(record, "agent_name", None),
                "task_id": getattr(record, "task_id", None),
                "agent_id": getattr(record, "agent_id", None),
            }
        )
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def render_log_record(line: str) -> str:
    """Render a structured log line for reports while tolerating legacy text lines."""
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return line
    return f"{record.get('timestamp', '')} - {record.get('logger', '')} - {record.get('level', '')} - {record.get('message', '')}"


def _initialize_logging():
    global logging_initialized
    if config.GOOGLE_CLOUD_LOGGING_ENABLED:
        import google.cloud.logging

        client = google.cloud.logging.Client()
        client.setup_logging()
    else:
        handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
        if config.LOG_TO_FILE:
            handlers.append(_build_file_log_handler())
        formatter = StructuredJsonFormatter()
        for handler in handlers:
            handler.setFormatter(formatter)
            handler.addFilter(StructuredLogFilter())
        logging.basicConfig(handlers=handlers)
    logging_initialized = True


def _build_file_log_handler() -> logging.Handler:
    """Create a rotating file handler writing to ``<LOG_DIR>/<service>.log``.

    The service name is derived from the entry script's package (e.g. ``orchestrator/main.py`` -> ``orchestrator``),
    so each service gets its own file without per-service configuration.
    """
    from logging.handlers import RotatingFileHandler

    service_name = Path(sys.argv[0]).resolve().parent.name or "app"
    log_dir = Path(config.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    return RotatingFileHandler(
        log_dir / f"{service_name}.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )


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


def get_execution_logs_from_artifacts(artifacts: list[FileArtifact], log_filename_pattern: str = "logs") -> list[str]:
    if not artifacts:
        return []

    logs = []
    for artifact in artifacts:
        if (
            artifact.name
            and (log_filename_pattern.lower() in artifact.name.lower())
            and (artifact.name.endswith(".txt") or artifact.name.endswith(".log"))
            and artifact.raw
        ):
            try:
                logs.append(artifact.raw.decode("utf-8"))
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
        parsed = parser.parse(cleaned_timestamp)
        # Timestamps without an offset are treated as UTC, so every consumer works with the same instant.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (OverflowError, TypeError, ValueError) as e:
        get_logger(__name__).warning(
            f"Ignoring invalid timestamp value for '{field_name}': '{timestamp_str}'. Error: {e}"
        )
        return None

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import json
import logging
import mimetypes
import os
import re
import sys
from collections.abc import Mapping
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

import httpx
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
    pattern like ``report`` behaves like the old substring match. An invalid, over-long
    or exponentially backtracking pattern raises a clear error.
    """
    if len(pattern) > MAX_NAME_PATTERN_LENGTH:
        raise ValueError(f"Name pattern exceeds the {MAX_NAME_PATTERN_LENGTH}-character limit.")
    if _has_nested_quantifier(pattern):
        raise ValueError(
            f"Name pattern '{pattern}' quantifies a group that already repeats (e.g. '(a+)+'), which can "
            "take exponential time to match. Rewrite it without the nested repetition."
        )
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        raise ValueError(f"Invalid name pattern '{pattern}': {e}") from e


def _has_nested_quantifier(pattern: str) -> bool:
    """Whether a repeated group of ``pattern`` itself repeats, as in ``(a+)+``.

    That shape makes the backtracking engine explore exponentially many splits of the subject, so a
    pattern carrying it can hang the process on a name of a few dozen characters. Escapes and
    character classes are skipped, because a quantifier inside them is a literal.
    """
    repeats_in_group: list[bool] = []
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "\\":
            index += 2
            continue
        if character == "[":
            closing = pattern.find("]", index + 1)
            if closing == -1:
                return False
            index = closing + 1
            continue
        if character == "(":
            repeats_in_group.append(False)
        elif character == ")" and repeats_in_group:
            group_repeats = repeats_in_group.pop()
            quantified = pattern[index + 1 : index + 2] in ("*", "+", "{")
            if group_repeats and quantified:
                return True
            if repeats_in_group and (group_repeats or quantified):
                repeats_in_group[-1] = True
        elif character in ("*", "+") and repeats_in_group:
            repeats_in_group[-1] = True
        index += 1
    return False


def is_same_origin(url: str, base_url: str) -> bool:
    """Whether ``url`` has the same scheme, host and port as ``base_url``.

    The check parses both with httpx, the client that sends the request, so the two agree:
    httpx lower-cases scheme and host and reports a scheme's default port as None, making
    ``https://host`` and ``https://host:443`` one origin. A URL the client would refuse
    (a control character, invalid IDNA, a lone surrogate) is never the same origin.

    Every call site that attaches credentials to a URL taken from response data uses this,
    so the configured service's credentials can't be sent to another origin.
    """

    def origin(value: str) -> tuple[str, str, int | None]:
        # httpx decodes the host lazily, so the attribute access is part of the parse.
        parsed = httpx.URL(value)
        return parsed.scheme, parsed.host, parsed.port

    try:
        return origin(url) == origin(base_url)
    except (httpx.InvalidURL, UnicodeError):
        return False


def retry_delay(retry_after: str | None, attempt: int, cap: float) -> float:
    """Seconds to wait before the next attempt, honouring ``Retry-After`` within ``cap``.

    ``Retry-After`` is legally delta-seconds *or* an HTTP-date (RFC 9110 § 10.2.3), and
    comes from outside, so an unparsable value falls back to the exponential back-off and
    the cap bounds the wait either way.
    """
    if retry_after:
        try:
            return min(float(retry_after), cap)
        except ValueError:
            pass
    return min(2**attempt, cap)


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
        custom = {
            key: value
            for key, value in record.__dict__.items()
            if key not in standard and key not in self._CANONICAL_FIELDS
        }
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


def parse_log_record(line: str) -> dict[str, object] | None:
    """Parse one structured (JSON) log line; None for a plain-text line of another format."""
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) and "message" in record else None


def render_log_message(record: Mapping[str, object]) -> str:
    """The readable message of a structured record, followed by its exception text when it has one."""
    message = str(record.get("message", ""))
    exception = record.get("exception")
    return f"{message}\n{exception}" if exception else message


def render_log_record(line: str) -> str:
    """Render a structured log line as a readable line while leaving lines of other formats untouched."""
    record = parse_log_record(line)
    if record is None:
        return line
    return (
        f"{record.get('timestamp', '')} - {record.get('logger', '')} - {record.get('level', '')} - "
        f"{render_log_message(record)}"
    )


def render_log_text(text: str) -> str:
    """Render every line of a log chunk, so reports never show raw machine output."""
    return "\n".join(render_log_record(line) for line in text.splitlines())


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
            and (artifact.name.endswith(".txt") or artifact.name.endswith(".log") or artifact.name.endswith(".md"))
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

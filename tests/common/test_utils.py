# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import mimetypes
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest
from pydantic_ai import BinaryContent

from common import utils


# Mock config
@pytest.fixture(autouse=True)
def mock_config(monkeypatch):
    monkeypatch.setattr("config.GOOGLE_CLOUD_LOGGING_ENABLED", False)
    monkeypatch.setattr("config.LOG_LEVEL", "INFO")


def test_get_logger_local():
    logger = utils.get_logger("test_logger")
    assert logger.name == "test_logger"
    assert logger.level == 20  # INFO


@patch("common.utils.config.GOOGLE_CLOUD_LOGGING_ENABLED", True)
@patch("google.cloud.logging.Client")
def test_get_logger_cloud(mock_client_cls):
    utils.logging_initialized = False  # Reset to force re-init
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    logger = utils.get_logger("cloud_logger")
    mock_client.setup_logging.assert_called_once()
    assert logger.name == "cloud_logger"


def test_fetch_media_file_content_from_local_file_exists():
    with (
        patch("pathlib.Path.is_file", return_value=True),
        patch("pathlib.Path.read_bytes", return_value=b"test data"),
        patch("mimetypes.guess_type", return_value=("image/png", None)),
    ):
        content = utils.fetch_media_file_content_from_local("test.png", "/tmp")
        assert isinstance(content, BinaryContent)
        assert content.data == b"test data"
        assert content.media_type == "image/png"


def test_fetch_media_file_content_from_local_file_not_found():
    with patch("pathlib.Path.is_file", return_value=False), pytest.raises(RuntimeError, match="does not exist"):
        utils.fetch_media_file_content_from_local("test.png", "/tmp")


def test_fetch_media_file_content_from_local_invalid_mime():
    with (
        patch("pathlib.Path.is_file", return_value=True),
        patch("mimetypes.guess_type", return_value=("text/plain", None)),
        pytest.raises(RuntimeError, match="not a media file"),
    ):
        utils.fetch_media_file_content_from_local("test.md", "/tmp")


def test_parse_timestamp_cleans_trailing_comma_content():
    timestamp = utils.parse_timestamp(
        "2026-05-04T10:33:56.442422967+00:00,expectedResults:", "step execution start timestamp"
    )

    assert timestamp is not None
    assert timestamp.year == 2026
    assert timestamp.microsecond == 442422
    assert timestamp.utcoffset().total_seconds() == 0


@pytest.mark.parametrize(
    "timestamp_str",
    [
        "2026-05-04T10:33:56",
        "2026-05-04T12:33:56+02:00",
        "2026-05-04T10:33:56Z",
    ],
)
def test_parse_timestamp_normalizes_to_the_same_utc_instant(timestamp_str):
    timestamp = utils.parse_timestamp(timestamp_str, "step execution start timestamp")

    assert timestamp == datetime(2026, 5, 4, 10, 33, 56, tzinfo=UTC)


def test_parse_timestamp_returns_none_for_invalid_value():
    assert utils.parse_timestamp("not-a-timestamp", "step execution start timestamp") is None


_STRUCTURED_LINE = (
    '{"timestamp": "2026-05-04T10:33:56+00:00", "level": "INFO", "severity": "INFO", "message": "Step done", '
    '"logger": "ui_agent", "module": "main", "line": 7, "agent_name": "UI Agent", "task_id": "t-1", "agent_id": null}'
)


def test_render_log_record_turns_a_structured_line_into_a_readable_line():
    assert utils.render_log_record(_STRUCTURED_LINE) == "2026-05-04T10:33:56+00:00 - ui_agent - INFO - Step done"


def test_render_log_record_appends_the_exception_text():
    line = '{"timestamp": "t", "level": "ERROR", "message": "Failed", "logger": "a", "exception": "Traceback: boom"}'

    assert utils.render_log_record(line) == "t - a - ERROR - Failed\nTraceback: boom"


@pytest.mark.parametrize(
    "line",
    ["2026-01-01 12:00:00,000 - agent - INFO - legacy text", "12:00:00.123 INFO Logger - logback", "[1, 2]", "{}"],
    ids=["python-text", "logback", "json-non-record", "json-without-message"],
)
def test_render_log_record_leaves_lines_of_other_formats_untouched(line):
    assert utils.render_log_record(line) == line


def test_render_log_text_renders_every_line_of_a_mixed_chunk():
    chunk = f"{_STRUCTURED_LINE}\nplain text line"

    assert utils.render_log_text(chunk) == "2026-05-04T10:33:56+00:00 - ui_agent - INFO - Step done\nplain text line"


@pytest.mark.parametrize(
    "pattern",
    ["report", r"^spec.*\.pdf$", "(draft|final)", "a{2,4}b", "[*+]+", r"\(a+\)+"],
)
def test_compile_name_pattern_accepts_ordinary_patterns(pattern):
    assert utils.compile_name_pattern(pattern).search is not None


@pytest.mark.parametrize(
    "pattern",
    ["(a+)+", "(a+)+b", "((a*)*)", "(x(y+))+"],
    ids=["plain", "with_suffix", "star_in_star", "quantifier_one_level_down"],
)
def test_compile_name_pattern_rejects_exponential_backtracking(pattern):
    with pytest.raises(ValueError, match="nested repetition"):
        utils.compile_name_pattern(pattern)


def test_compile_name_pattern_rejects_an_over_long_pattern():
    with pytest.raises(ValueError, match="character limit"):
        utils.compile_name_pattern("a" * (utils.MAX_NAME_PATTERN_LENGTH + 1))


def test_compile_name_pattern_rejects_an_uncompilable_pattern():
    with pytest.raises(ValueError, match="Invalid name pattern"):
        utils.compile_name_pattern("([unclosed")

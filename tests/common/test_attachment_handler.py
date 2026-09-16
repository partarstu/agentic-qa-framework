# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the attachment_handler module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from common import attachment_handler


class TestShouldSkipAttachment:
    """Tests for the should_skip_attachment function."""

    def test_skip_attachment_with_default_postfix(self):
        """Test file with _SKIP postfix is skipped."""
        with patch.object(attachment_handler.config, "JIRA_ATTACHMENT_SKIP_POSTFIX", "_SKIP"):
            assert attachment_handler.should_skip_attachment("mockup_SKIP.png") is True

    def test_skip_attachment_case_insensitive(self):
        """Test skip postfix comparison is case-insensitive."""
        with patch.object(attachment_handler.config, "JIRA_ATTACHMENT_SKIP_POSTFIX", "_SKIP"):
            assert attachment_handler.should_skip_attachment("mockup_skip.png") is True
            assert attachment_handler.should_skip_attachment("mockup_Skip.png") is True

    def test_no_skip_normal_file(self):
        """Test normal file without skip postfix is not skipped."""
        with patch.object(attachment_handler.config, "JIRA_ATTACHMENT_SKIP_POSTFIX", "_SKIP"):
            assert attachment_handler.should_skip_attachment("mockup.png") is False

    def test_no_skip_empty_postfix(self):
        """Test no files are skipped when postfix is empty."""
        with patch.object(attachment_handler.config, "JIRA_ATTACHMENT_SKIP_POSTFIX", ""):
            assert attachment_handler.should_skip_attachment("mockup_SKIP.png") is False

    def test_skip_with_custom_postfix(self):
        """Test skip works with custom postfix."""
        assert attachment_handler.should_skip_attachment("file_IGNORE.pdf", "_IGNORE") is True
        assert attachment_handler.should_skip_attachment("file.pdf", "_IGNORE") is False


class TestIsSupportedMimeType:
    """Tests for the is_supported_mime_type function."""

    def test_supported_image_types(self):
        """Test common image MIME types are supported."""
        assert attachment_handler.is_supported_mime_type("image/png") is True
        assert attachment_handler.is_supported_mime_type("image/jpeg") is True
        assert attachment_handler.is_supported_mime_type("image/gif") is True
        assert attachment_handler.is_supported_mime_type("image/webp") is True

    def test_supported_audio_types(self):
        """Test common audio MIME types are supported."""
        assert attachment_handler.is_supported_mime_type("audio/mpeg") is True
        assert attachment_handler.is_supported_mime_type("audio/wav") is True
        assert attachment_handler.is_supported_mime_type("audio/ogg") is True

    def test_supported_video_types(self):
        """Test common video MIME types are supported."""
        assert attachment_handler.is_supported_mime_type("video/mp4") is True
        assert attachment_handler.is_supported_mime_type("video/webm") is True

    def test_supported_document_types(self):
        """Test common document MIME types are supported."""
        assert attachment_handler.is_supported_mime_type("application/pdf") is True
        assert attachment_handler.is_supported_mime_type("text/plain") is True

    def test_unsupported_mime_types(self):
        """Test unsupported MIME types return False."""
        assert attachment_handler.is_supported_mime_type("application/zip") is False
        assert attachment_handler.is_supported_mime_type("application/x-rar") is False
        assert attachment_handler.is_supported_mime_type("application/octet-stream") is False

    def test_types_not_in_config_whitelist(self):
        """Test document types not in config.SUPPORTED_ATTACHMENT_MIME_TYPES are filtered."""
        # These are in Pydantic AI's DocumentMediaType but not in the config whitelist
        assert (
            attachment_handler.is_supported_mime_type(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            is False
        )  # .docx
        assert (
            attachment_handler.is_supported_mime_type(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            is False
        )  # .xlsx
        assert attachment_handler.is_supported_mime_type("application/vnd.ms-excel") is False  # .xls
        assert attachment_handler.is_supported_mime_type("text/csv") is False  # .csv
        assert attachment_handler.is_supported_mime_type("text/html") is False  # .html
        assert attachment_handler.is_supported_mime_type("text/markdown") is False  # .md

    def test_none_mime_type(self):
        """Test None MIME type returns False."""
        assert attachment_handler.is_supported_mime_type(None) is False

# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the attachment_handler module."""

from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from pydantic_ai.messages import BinaryContent

from common import attachment_handler


class TestGetMimeType:
    """Tests for the get_mime_type function."""

    def test_get_mime_type_from_extension_png(self):
        """Test MIME type detection from .png extension."""
        mime_type = attachment_handler.get_mime_type("image.png")
        assert mime_type == "image/png"

    def test_get_mime_type_from_extension_pdf(self):
        """Test MIME type detection from .pdf extension."""
        mime_type = attachment_handler.get_mime_type("document.pdf")
        assert mime_type == "application/pdf"

    def test_get_mime_type_from_extension_jpeg(self):
        """Test MIME type detection from .jpeg extension."""
        mime_type = attachment_handler.get_mime_type("photo.jpeg")
        assert mime_type == "image/jpeg"

    def test_get_mime_type_from_extension_mp4(self):
        """Test MIME type detection from .mp4 extension."""
        mime_type = attachment_handler.get_mime_type("video.mp4")
        assert mime_type == "video/mp4"

    def test_get_mime_type_no_extension_no_bytes(self):
        """Test MIME type detection fails without extension or bytes."""
        mime_type = attachment_handler.get_mime_type("file_without_extension")
        assert mime_type is None

    @patch("common.attachment_handler.magic")
    def test_get_mime_type_using_magic(self, mock_magic):
        """Test MIME type detection from file using python-magic."""
        mock_magic.from_file.return_value = "image/png"

        mime_type = attachment_handler.get_mime_type("file_without_extension")

        mock_magic.from_file.assert_called_once_with("file_without_extension", mime=True)
        assert mime_type == "image/png"


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
        assert attachment_handler.is_supported_mime_type("application/vnd.openxmlformats-officedocument.wordprocessingml.document") is False  # .docx
        assert attachment_handler.is_supported_mime_type("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") is False  # .xlsx
        assert attachment_handler.is_supported_mime_type("application/vnd.ms-excel") is False  # .xls
        assert attachment_handler.is_supported_mime_type("text/csv") is False  # .csv
        assert attachment_handler.is_supported_mime_type("text/html") is False  # .html
        assert attachment_handler.is_supported_mime_type("text/markdown") is False  # .md

    def test_none_mime_type(self):
        """Test None MIME type returns False."""
        assert attachment_handler.is_supported_mime_type(None) is False


class TestFetchAllAttachments:
    """Tests for the fetch_all_attachments function."""

    @patch.object(attachment_handler, "_fetch_file_bytes")
    @patch.object(attachment_handler.config, "JIRA_ATTACHMENT_SKIP_POSTFIX", "_SKIP")
    def test_fetch_valid_attachments(self, mock_fetch_bytes):
        """Test fetching valid attachments returns BinaryContent list."""
        mock_fetch_bytes.return_value = (b"fake image data", "image.png")
        
        result = attachment_handler.fetch_all_attachments(["path/to/image.png"])
        
        assert len(result) == 1
        assert "image.png" in result
        assert isinstance(result["image.png"], BinaryContent)
        assert result["image.png"].media_type == "image/png"
        assert result["image.png"].identifier == "image.png"

    @patch.object(attachment_handler, "_fetch_file_bytes")
    @patch.object(attachment_handler.config, "JIRA_ATTACHMENT_SKIP_POSTFIX", "_SKIP")
    def test_skip_files_with_postfix(self, mock_fetch_bytes):
        """Test files with skip postfix are not included."""
        mock_fetch_bytes.return_value = (b"fake data", "image_SKIP.png")
        
        result = attachment_handler.fetch_all_attachments(["path/to/image_SKIP.png"])
        
        assert len(result) == 0
        mock_fetch_bytes.assert_not_called()

    @patch.object(attachment_handler, "_fetch_file_bytes")
    @patch.object(attachment_handler.config, "JIRA_ATTACHMENT_SKIP_POSTFIX", "_SKIP")
    def test_skip_unsupported_mime_types(self, mock_fetch_bytes):
        """Test files with unsupported MIME types are not included."""
        mock_fetch_bytes.return_value = (b"fake zip data", "archive.zip")
        
        result = attachment_handler.fetch_all_attachments(["path/to/archive.zip"])
        
        assert len(result) == 0

    @patch.object(attachment_handler, "_fetch_file_bytes")
    @patch.object(attachment_handler.config, "JIRA_ATTACHMENT_SKIP_POSTFIX", "_SKIP")
    def test_mixed_valid_and_invalid_attachments(self, mock_fetch_bytes):
        """Test mixed valid and invalid attachments returns only valid ones."""
        def side_effect(path):
            filename = Path(path).name
            return (b"fake data", filename)
        
        mock_fetch_bytes.side_effect = side_effect
        
        paths = [
            "path/to/image.png",
            "path/to/mockup_SKIP.jpg",
            "path/to/archive.zip",
            "path/to/document.pdf"
        ]
        
        result = attachment_handler.fetch_all_attachments(paths)
        
        assert len(result) == 2
        assert "image.png" in result
        assert "document.pdf" in result

    @patch.object(attachment_handler, "_fetch_file_bytes")
    @patch.object(attachment_handler.config, "JIRA_ATTACHMENT_SKIP_POSTFIX", "_SKIP")
    def test_handle_fetch_errors_gracefully(self, mock_fetch_bytes):
        """Test errors during fetch are handled gracefully."""
        mock_fetch_bytes.side_effect = RuntimeError("File not found")
        
        result = attachment_handler.fetch_all_attachments(["path/to/missing.png"])
        
        assert len(result) == 0

    def test_empty_attachment_list(self):
        """Test empty attachment list returns empty result."""
        result = attachment_handler.fetch_all_attachments([])
        assert result == {}

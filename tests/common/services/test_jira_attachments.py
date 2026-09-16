# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the REST attachment downloader and shared Jira client factory (WS5)."""

from unittest.mock import MagicMock, patch

import pytest

from common.services.jira_attachments import download_issue_attachments
from common.services.jira_client import build_jira_client


def test_build_jira_client_raises_on_missing_config():
    with patch("common.services.jira_client.config") as mock_config:
        mock_config.JIRA_BASE_URL = ""
        with pytest.raises(RuntimeError, match="Jira configuration is missing"):
            build_jira_client()


def test_build_jira_client_passes_basic_auth():
    with patch("common.services.jira_client.config") as mock_config, patch(
        "common.services.jira_client.JIRA"
    ) as mock_jira:
        mock_config.JIRA_BASE_URL = "https://jira.example.com"
        mock_config.JIRA_USER = "user"
        mock_config.JIRA_TOKEN = "token"
        build_jira_client()
    mock_jira.assert_called_once_with(server="https://jira.example.com", basic_auth=("user", "token"))


def _attachment(filename: str, mime_type: str, content: str = "/rest/api/2/attachment/content/1"):
    attachment = MagicMock()
    attachment.filename = filename
    attachment.mimeType = mime_type
    attachment.content = content
    return attachment


def _issue_with(attachments) -> MagicMock:
    issue = MagicMock()
    issue.fields.attachment = attachments
    return issue


@patch("common.services.jira_attachments.config")
@patch("common.services.jira_attachments.httpx.get")
@patch("common.services.jira_attachments.build_jira_client")
def test_downloads_supported_attachments_as_text_equivalents(mock_client, mock_get, mock_config):
    mock_config.JIRA_BASE_URL = "https://jira.example.com"
    mock_config.JIRA_USER = "user"
    mock_config.JIRA_TOKEN = "token"
    mock_client.return_value.issue.return_value = _issue_with([_attachment("data.json", "application/json")])
    mock_get.return_value.content = b'{"id": 1}'
    mock_get.return_value.raise_for_status = lambda: None

    result = download_issue_attachments("PROJ-1")

    assert list(result) == ["data.json"]
    assert result["data.json"].media_type == "text/plain"
    assert result["data.json"].data == b'{"id": 1}'
    mock_get.assert_called_once_with(
        "https://jira.example.com/rest/api/2/attachment/content/1",
        auth=("user", "token"),
        follow_redirects=True,
    )


@patch("common.services.jira_attachments.config")
@patch("common.services.jira_attachments.httpx.get")
@patch("common.services.jira_attachments.build_jira_client")
def test_skips_unsupported_and_postfixed_attachments(mock_client, mock_get, mock_config):
    mock_config.JIRA_BASE_URL = "https://jira.example.com"
    mock_config.JIRA_USER = "user"
    mock_config.JIRA_TOKEN = "token"
    mock_client.return_value.issue.return_value = _issue_with(
        [_attachment("archive.zip", "application/zip"), _attachment("diagram_SKIP.png", "image/png")]
    )
    mock_get.return_value.content = b"bytes"
    mock_get.return_value.raise_for_status = lambda: None

    assert download_issue_attachments("PROJ-1") == {}
    # The postfixed attachment is dropped before downloading; the unsupported one after it.
    mock_get.assert_called_once()


@patch("common.services.jira_attachments.httpx.get")
@patch("common.services.jira_attachments.build_jira_client")
def test_issue_without_attachments_yields_empty_dict(mock_client, mock_get):
    mock_client.return_value.issue.return_value = _issue_with(None)
    assert download_issue_attachments("PROJ-1") == {}

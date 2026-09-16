# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""REST download of a Jira issue's attachments as model-ready binary content (WS5).

Replaces the previous MCP message-scanning path: agents download the attachments
of the issue being processed directly over the Jira REST API and hand them to the
model as ``BinaryContent``, applying the same predicates as before (skip postfix,
supported MIME type, text-equivalent media types).
"""

import httpx
from pydantic_ai.messages import BinaryContent

import config
from common import utils
from common.attachment_handler import as_text_equivalent, is_supported_mime_type, should_skip_attachment
from common.services.jira_client import build_jira_client

logger = utils.get_logger("jira_attachments")


def _download(attachment) -> bytes:
    """Downloads one attachment's content with basic auth.

    Jira Cloud returns the attachment's ``content`` field as an absolute URL, so it
    is used as-is; a relative path (seen on Data Center setups) resolves against the
    base URL.
    """
    content_url = attachment.content
    if not content_url.startswith(("http://", "https://")):
        content_url = f"{config.JIRA_BASE_URL}{content_url}"
    response = httpx.get(
        content_url,
        auth=(config.JIRA_USER, config.JIRA_TOKEN),
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.content


def download_issue_attachments(issue_key: str) -> dict[str, BinaryContent]:
    """Downloads the supported attachments of a Jira issue over the REST API.

    Args:
        issue_key: The key of the Jira issue (e.g. ``PROJ-123``).

    Returns:
        Dictionary mapping file name to BinaryContent for every supported attachment.
    """
    jira = build_jira_client()
    issue = jira.issue(issue_key, fields="attachment")
    attachments: dict[str, BinaryContent] = {}
    for attachment in getattr(issue.fields, "attachment", None) or []:
        filename = attachment.filename
        if should_skip_attachment(filename):
            logger.info("Skipping attachment '%s' due to skip postfix.", filename)
            continue
        content = _download(attachment)
        binary = as_text_equivalent(BinaryContent(data=content, media_type=attachment.mimeType, identifier=filename))
        if not is_supported_mime_type(binary.media_type):
            logger.info("Skipping attachment '%s' - unsupported MIME type: %s", filename, attachment.mimeType)
            continue
        attachments[filename] = binary
    logger.info("Downloaded %d attachment(s) of %s over REST.", len(attachments), issue_key)
    return attachments

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""REST download of a Jira issue's attachments as model-ready binary content (WS5).

Replaces the previous MCP message-scanning path: agents download the attachments
of the issue being processed directly over the Jira REST API and hand them to the
model as ``BinaryContent``, applying the same predicates as before (skip postfix,
supported MIME type, text-equivalent media types).
"""

import re

import httpx
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import BinaryContent

import config
from common import utils
from common.attachment_handler import as_text_equivalent, is_supported_mime_type, should_skip_attachment
from common.services.jira_client import build_jira_client

logger = utils.get_logger("jira_attachments")

# Jira issue keys are a project key, a hyphen and the issue number, e.g. PROJ-123.
_ISSUE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")


def require_valid_issue_key(issue_key: str) -> None:
    """Rejects an issue key that the model made up or smuggled a path into.

    Raises:
        ModelRetry: When the key does not have the Jira issue key format. Raised as a retry, not
            as a hard error, so the model can correct the key instead of failing the whole task.
    """
    if not _ISSUE_KEY_PATTERN.fullmatch(issue_key):
        raise ModelRetry(
            f"'{issue_key[:50]}' is not a Jira issue key. Pass the key of the issue you are working on, "
            "in the format PROJ-123."
        )


def _origin(url: str) -> tuple[str, str, int | None]:
    """Scheme, host and port of a URL as the HTTP client parses them.

    httpx lower-cases scheme and host and reports a scheme's default port as None, so
    ``https://host`` and ``https://host:443`` share an origin.

    Raises:
        httpx.InvalidURL: When the client would refuse the URL (e.g. a control character).
        UnicodeError: When the host is invalid IDNA/punycode or the URL holds a lone surrogate.
    """
    parsed = httpx.URL(url)
    return parsed.scheme, parsed.host, parsed.port


def _resolve_content_url(content: str) -> str | None:
    """Resolves an attachment's ``content`` field to the URL to download, or None when it is untrusted.

    Jira Cloud returns an absolute URL; a relative path (seen on Data Center setups) is
    appended to the base URL. Either way the resulting URL is used only when its scheme,
    host and port match the configured base URL, so the credentials never reach another
    origin (a crafted relative path such as ``@other-host/...`` changes the host too).
    The check parses URLs with httpx, the client that sends the request, so both agree.
    """
    try:
        url = content if httpx.URL(content).scheme else f"{config.JIRA_BASE_URL}{content}"
        is_same_origin = _origin(url) == _origin(config.JIRA_BASE_URL)
    except (httpx.InvalidURL, UnicodeError):
        # URLs the client would refuse are untrusted as well.
        return None
    return url if is_same_origin else None


def _download(content_url: str) -> bytes:
    """Downloads one attachment's content with basic auth."""
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
        issue_key: The key of the Jira issue (e.g. ``PROJ-123``). It comes from the model, so it is
            validated before it reaches the Jira REST path.

    Returns:
        Dictionary mapping file name to BinaryContent for every supported attachment.

    Raises:
        ModelRetry: When the key does not have the Jira issue key format, so the model can correct it.
    """
    require_valid_issue_key(issue_key)
    jira = build_jira_client()
    issue = jira.issue(issue_key, fields="attachment")
    attachments: dict[str, BinaryContent] = {}
    for attachment in getattr(issue.fields, "attachment", None) or []:
        filename = attachment.filename
        if should_skip_attachment(filename):
            logger.info("Skipping attachment '%s' due to skip postfix.", filename)
            continue
        content_url = _resolve_content_url(attachment.content)
        if content_url is None:
            logger.warning("Skipping attachment '%s' - its content URL is not on the configured Jira origin.", filename)
            continue
        content = _download(content_url)
        binary = as_text_equivalent(BinaryContent(data=content, media_type=attachment.mimeType, identifier=filename))
        if not is_supported_mime_type(binary.media_type):
            logger.info("Skipping attachment '%s' - unsupported MIME type: %s", filename, attachment.mimeType)
            continue
        attachments[filename] = binary
    logger.info("Downloaded %d attachment(s) of %s over REST.", len(attachments), issue_key)
    return attachments

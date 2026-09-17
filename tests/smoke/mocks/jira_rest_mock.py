# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Minimal recording mock for the Jira REST API.

The ``jira`` Python client (``JIRA(server, basic_auth=...)``) probes ``myself`` and
``serverInfo`` on construction, then posts comments to
``/rest/api/2/issue/{key}/comment`` (``add_jira_comment``), runs JQL searches
against ``/rest/api/2/search`` (the RAG sync) and, since WS5, serves the issue's
attachment metadata and content downloads for the agents' REST attachment
downloader. Every recorded comment and download is exposed at ``GET /__recorded``
for the smoke assertions.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI()

_recorded_comments: list[dict[str, str]] = []
_recorded_attachment_downloads: list[dict[str, str]] = []

# The same story the Jira MCP mock seeds (jira_mcp_mock._SEEDED_STORY), in the raw
# shape the jira client's search API returns. Its status must be one of
# config.QdrantConfig.VALID_STATUSES so the RAG sync treats it as active.
_SEEDED_SEARCH_ISSUE = {
    "id": "10001",
    "key": "SMOKE-1",
    "self": "http://jira_rest_mock:8080/rest/api/2/issue/10001",
    "fields": {
        "summary": "User can reset their password via an emailed link",
        "description": (
            "As a registered user I want to reset my password through a link sent to my email "
            "so that I can regain access when I forget it."
        ),
        "status": {"name": "To Do"},
        "issuetype": {"name": "Story"},
        "updated": "2026-01-01T00:00:00.000+0000",
    },
}

# The seeded story's attachments, mirroring jira_mcp_mock's: a plain-text policy and a
# JSON attachment (served under a text-equivalent media type by the downloader). The
# ``content`` field is the ABSOLUTE URL Jira Cloud returns (WS5 downloader uses it as-is).
_ATTACHMENTS = [
    {
        "id": "10001",
        "filename": "reset-policy.md",
        "mimeType": "text/plain",
        "size": 116,
        "content": "http://jira_rest_mock:8080/rest/api/2/attachment/content/10001",
    },
    {
        "id": "10002",
        "filename": "reset-request.json",
        "mimeType": "application/json",
        "size": 45,
        "content": "http://jira_rest_mock:8080/rest/api/2/attachment/content/10002",
    },
]
_ATTACHMENT_CONTENT = {
    "reset-policy.md": (
        b"Password reset policy\n"
        b"- A reset link stays valid for 60 minutes.\n"
        b"- At most 3 reset requests per account per hour.\n"
    ),
    "reset-request.json": b'{"email": "user@example.com", "locale": "en-GB"}',
}


@app.get("/rest/api/2/myself")
async def myself() -> dict[str, str]:
    return {"name": "smoke", "key": "smoke", "accountId": "smoke", "displayName": "Smoke User"}


@app.get("/rest/api/2/serverInfo")
async def server_info(request: Request) -> dict:
    return {
        "baseUrl": str(request.base_url).rstrip("/"),
        "version": "9.4.0",
        "versionNumbers": [9, 4, 0],
        "deploymentType": "Server",
    }


@app.get("/rest/api/2/issue/{issue_key}")
async def get_issue(issue_key: str, request: Request) -> dict:
    """Serves the issue with its attachment metadata (the WS5 REST downloader's read)."""
    return {
        "id": "10001",
        "key": issue_key,
        "self": f"{request.base_url}rest/api/2/issue/10001",
        "fields": {"attachment": _ATTACHMENTS},
    }


@app.get("/rest/api/2/attachment/content/{attachment_id}")
async def download_attachment(attachment_id: str) -> Response:
    """Serves one attachment's bytes and records the download for the smoke assertions."""
    attachment = next((a for a in _ATTACHMENTS if a["id"] == attachment_id), None)
    if attachment is None:
        return Response(status_code=404)
    _recorded_attachment_downloads.append({"attachment_id": attachment_id, "filename": attachment["filename"]})
    return Response(content=_ATTACHMENT_CONTENT[attachment["filename"]], media_type=attachment["mimeType"])


@app.post("/rest/api/2/issue/{issue_key}/comment")
async def add_comment(issue_key: str, request: Request) -> JSONResponse:
    payload = await request.json()
    body = (payload or {}).get("body", "")
    _recorded_comments.append({"issue_key": issue_key, "body": body})
    comment_id = str(10000 + len(_recorded_comments))
    return JSONResponse(
        {
            "id": comment_id,
            "self": f"{request.base_url}rest/api/2/issue/{issue_key}/comment/{comment_id}",
            "body": body,
        }
    )


@app.get("/rest/api/2/search")
async def search_issues() -> dict:
    """Answer every JQL search with the seeded story (the RAG sync searches twice:
    all issue ids for reconciliation, then issues updated since the watermark)."""
    return {"expand": "", "startAt": 0, "maxResults": 50, "total": 1, "issues": [_SEEDED_SEARCH_ISSUE]}


@app.get("/__recorded")
async def recorded() -> dict:
    return {"comments": _recorded_comments, "attachment_downloads": _recorded_attachment_downloads}


@app.get("/rest/api/2/{path:path}")
async def catch_all(path: str) -> dict:
    """Answer any other probe the client makes during init so it does not error out."""
    return {}

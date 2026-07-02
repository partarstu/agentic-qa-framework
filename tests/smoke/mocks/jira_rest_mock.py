# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Minimal recording mock for the Jira REST API.

The ``jira`` Python client (``JIRA(server, basic_auth=...)``) probes ``myself`` and
``serverInfo`` on construction, then posts comments to
``/rest/api/2/issue/{key}/comment`` (``add_jira_comment``) and runs JQL searches
against ``/rest/api/2/search`` (the RAG sync). Every search answers with the same
seeded story the Jira MCP mock serves; every recorded comment is exposed at
``GET /__recorded`` for the smoke assertions.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

_recorded_comments: list[dict[str, str]] = []

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
    return {"comments": _recorded_comments}


@app.get("/rest/api/2/{path:path}")
async def catch_all(path: str) -> dict:
    """Answer any other probe the client makes during init so it does not error out."""
    return {}

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Minimal recording mock for the Jira REST API used by ``add_jira_comment``.

The ``jira`` Python client (``JIRA(server, basic_auth=...)``) probes ``myself`` and
``serverInfo`` on construction, then posts comments to
``/rest/api/2/issue/{key}/comment``. Only those calls are served; every recorded
comment is exposed at ``GET /__recorded`` for the smoke assertions.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

_recorded_comments: list[dict[str, str]] = []


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


@app.get("/__recorded")
async def recorded() -> dict:
    return {"comments": _recorded_comments}


@app.get("/rest/api/2/{path:path}")
async def catch_all(path: str) -> dict:
    """Answer any other probe the client makes during init so it does not error out."""
    return {}

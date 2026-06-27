# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Recording SSE MCP mock standing in for ``mcp-atlassian``.

Advertises the three Jira tools the agents rely on (``jira_get_issue``,
``jira_download_attachments``, ``jira_add_comment``) with names and descriptions
close to the real server so the model picks them. It seeds a single,
attachment-free user story (so no shared attachment volume is needed) and records
every ``jira_add_comment`` call for the smoke assertions.

The MCP SSE transport is served under ``/sse`` (+ ``/messages/``); a plain
``GET /__recorded`` HTTP route is mounted alongside it for introspection.
"""

import json

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

SEEDED_ISSUE_KEY = "SMOKE-1"

_SEEDED_STORY = {
    "key": SEEDED_ISSUE_KEY,
    "id": "10001",
    "fields": {
        "project": {"key": "SMOKE", "id": "10000"},
        "issuetype": {"name": "Story"},
        "summary": "User can reset their password via an emailed link",
        "description": (
            "As a registered user I want to reset my password through a link sent to my email "
            "so that I can regain access when I forget it.\n\n"
            "Project Key: SMOKE\n"
            "Issue ID (numeric): 10001\n\n"
            "Acceptance Criteria:\n"
            "1. A 'Forgot password' link on the login page opens a form that accepts an email address.\n"
            "2. Submitting a registered email sends a password-reset link that expires after 60 minutes.\n"
            "3. Submitting an unregistered email shows the same confirmation message (no account enumeration).\n"
            "4. Opening a valid link lets the user set a new password that must meet the complexity policy.\n"
            "5. An expired or already-used link shows an error and offers to request a new one."
        ),
        "attachment": [],
    },
}

_recorded: dict[str, list] = {"get_issue": [], "download_attachments": [], "comments": []}

# Agents reach this mock by its compose service-name host (e.g. "jira_mcp_mock:9000"),
# which the MCP SDK's DNS-rebinding protection rejects with 421 by default (it only
# allows localhost/127.0.0.1). Disable it: this is a test mock on a private network.
mcp = FastMCP(
    "jira-mock",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool()
async def jira_get_issue(issue_key: str) -> str:
    """Get the complete details of a Jira issue by its key (e.g. 'PROJ-123').

    Returns the issue as JSON, including its project, summary, description and
    acceptance criteria. Always call this first to read a Jira issue's content.
    """
    _recorded["get_issue"].append(issue_key)
    return json.dumps(_SEEDED_STORY)


@mcp.tool()
async def jira_download_attachments(issue_key: str, target_path: str) -> str:
    """Download all attachments of a Jira issue to a folder on the server.

    Returns a summary of what was downloaded. This issue has no attachments.
    """
    _recorded["download_attachments"].append({"issue_key": issue_key, "target_path": target_path})
    return f"Issue {issue_key} has no attachments to download. No files were written to {target_path}."


@mcp.tool()
async def jira_add_comment(issue_key: str, comment: str) -> str:
    """Add a comment to a Jira issue.

    Use this to post review feedback to a Jira issue identified by its key.
    """
    _recorded["comments"].append({"issue_key": issue_key, "comment": comment})
    return f"Successfully added comment to issue {issue_key}."


async def _recorded_endpoint(_request: Request) -> JSONResponse:
    return JSONResponse(_recorded)


app = Starlette(
    routes=[
        Route("/__recorded", _recorded_endpoint),
        Mount("/", app=mcp.sse_app()),
    ]
)

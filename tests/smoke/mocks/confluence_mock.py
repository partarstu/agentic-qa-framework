# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Stateful recording mock for the Confluence Cloud REST API v2 surface.

Serves the endpoints ``ConfluenceClient`` exercises: the space lookup by key,
the space page listing (cursor pagination), the single-page fetch with a storage
body and the per-page attachment listing (WS9b). The space seeds one page with
headings, paragraphs and a container macro; a small PDF and a PNG attachment ship
with WS9b and are listed already so the ingestion flow sees the full shape.

Everything recorded is exposed at ``GET /__recorded`` for the smoke assertions.
"""

from fastapi import FastAPI, Request

app = FastAPI()

SEEDED_SPACE_KEY = "SMOKEDOC"
SEEDED_SPACE_ID = "9001"
SEEDED_PAGE_ID = "6606"
SEEDED_PAGE_TITLE = "Password Reset Requirements"
# A page the requirements-review flow can find by content: headings, a container
# macro and a table, in storage format. The page title is the document's h1
# (added by the normalizer), so the body starts at h2 sections.
SEEDED_PAGE_BODY = (
    "<p>Overview of the password reset feature.</p>"
    "<h2>Reset Link Policy</h2>"
    "<ul><li>A reset link stays valid for 60 minutes.</li>"
    "<li>At most 3 reset requests per account per hour.</li></ul>"
    "<h2>Security Considerations</h2>"
    '<ac:structured-macro ac:name="info"><ac:rich-text-body>'
    "<p>Reset links are single-use and bound to the requesting session.</p>"
    "</ac:rich-text-body></ac:structured-macro>"
    "<h2>Rate Limits</h2>"
    "<table><tr><th>Scenario</th><th>Limit</th></tr>"
    "<tr><td>Requests per hour</td><td>3</td></tr></table>"
)

_SEEDED_PAGE = {
    "id": SEEDED_PAGE_ID,
    "status": "current",
    "title": SEEDED_PAGE_TITLE,
    "spaceId": SEEDED_SPACE_ID,
    "parentId": None,
    "version": {"createdAt": "2026-09-01T10:00:00Z", "number": 4},
    "body": {"storage": {"representation": "storage", "value": SEEDED_PAGE_BODY}},
    "_links": {"webui": f"/spaces/{SEEDED_SPACE_KEY}/pages/{SEEDED_PAGE_ID}"},
}

_SEEDED_ATTACHMENTS = [
    {
        "id": "att-1",
        "status": "current",
        "title": "reset-policy.pdf",
        "pageId": SEEDED_PAGE_ID,
        "mediaType": "application/pdf",
        "fileSize": 1024,
        "version": {"number": 1},
        "downloadLink": "/download/reset-policy.pdf",
    },
    {
        "id": "att-2",
        "status": "current",
        "title": "flow-diagram.png",
        "pageId": SEEDED_PAGE_ID,
        "mediaType": "image/png",
        "fileSize": 2048,
        "version": {"number": 1},
        "downloadLink": "/download/flow-diagram.png",
    },
]

_recorded: dict = {
    "space_lookups": [],
    "page_listings": [],
    "page_fetches": [],
    "attachment_listings": [],
    "attachment_downloads": [],
}


@app.get("/wiki/api/v2/spaces")
async def list_spaces(request: Request) -> dict:
    keys = request.query_params.getlist("keys")
    _recorded["space_lookups"].append({"keys": keys})
    results = []
    if SEEDED_SPACE_KEY in keys:
        results.append({"id": SEEDED_SPACE_ID, "key": SEEDED_SPACE_KEY, "name": "Smoke Documents"})
    return {"results": results, "_links": {"next": None}}


@app.get("/wiki/api/v2/spaces/{space_id}/pages")
async def list_pages(space_id: str, request: Request) -> dict:
    _recorded["page_listings"].append({"space_id": space_id, "cursor": request.query_params.get("cursor")})
    if space_id != SEEDED_SPACE_ID:
        return {"results": [], "_links": {"next": None}}
    return {
        "results": [
            {key: value for key, value in _SEEDED_PAGE.items() if key not in ("body",)}
        ],
        "_links": {"next": None},
    }


@app.get("/wiki/api/v2/pages/{page_id}")
async def get_page(page_id: str, request: Request) -> dict:
    _recorded["page_fetches"].append({"page_id": page_id, "body_format": request.query_params.get("body-format")})
    if page_id != SEEDED_PAGE_ID:
        return {"message": f"No page with id {page_id}"}
    return _SEEDED_PAGE


@app.get("/wiki/api/v2/pages/{page_id}/attachments")
async def list_attachments(page_id: str, request: Request) -> dict:
    _recorded["attachment_listings"].append(
        {"page_id": page_id, "filename": request.query_params.get("filename")}
    )
    if page_id != SEEDED_PAGE_ID:
        return {"results": [], "_links": {"next": None}}
    return {"results": _SEEDED_ATTACHMENTS, "_links": {"next": None}}


@app.get("/download/{filename}")
async def download_attachment(filename: str) -> bytes:
    _recorded["attachment_downloads"].append({"filename": filename})
    return b"%PDF-1.4 smoke attachment"


@app.get("/__recorded")
async def recorded() -> dict:
    return _recorded

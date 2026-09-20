# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Stateful recording mock for the Confluence Cloud REST API v2 surface.

Serves the endpoints ``ConfluenceClient`` exercises: the space lookup by key,
the space page listing (cursor pagination), the single-page fetch with a storage
body and the per-page attachment listing. The space seeds one page with
headings, paragraphs and a container macro; a small PDF and a PNG attachment are
listed already so the ingestion flow sees the full shape.

Everything recorded is exposed at ``GET /__recorded`` for the smoke assertions.
"""

import base64

from fastapi import FastAPI, Request
from fastapi.responses import Response

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

_PDF_BYTES = base64.b64decode(
    "JVBERi0xLjcKJcK1wrYKJSBXcml0dGVuIGJ5IE11UERGIDEuMjguMgoKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFIvSW5mbzw8L1Byb2R1Y2VyKE11UERGIDEuMjguMik+Pj4+CmVuZG9iagoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0NvdW50IDEvS2lkc1s0IDAgUl0+PgplbmRvYmoKCjMgMCBvYmoKPDwvRm9udDw8L2hlbHYgNSAwIFI+Pj4+CmVuZG9iagoKNCAwIG9iago8PC9UeXBlL1BhZ2UvTWVkaWFCb3hbMCAwIDU5NSA4NDJdL1JvdGF0ZSAwL1Jlc291cmNlcyAzIDAgUi9QYXJlbnQgMiAwIFIvQ29udGVudHNbNiAwIFJdPj4KZW5kb2JqCgo1IDAgb2JqCjw8L1R5cGUvRm9udC9TdWJ0eXBlL1R5cGUxL0Jhc2VGb250L0hlbHZldGljYS9FbmNvZGluZy9XaW5BbnNpRW5jb2Rpbmc+PgplbmRvYmoKCjYgMCBvYmoKPDwvTGVuZ3RoIDEyOS9GaWx0ZXIvRmxhdGVEZWNvZGU+PgpzdHJlYW0KeNodjLEKAkEMRPt8Rf7AbLI7cwdiIdjYCduJhXorFlrY+P3mJAwMj3mRj+y7FLW8onQlTftbNs/x+mop2h963jZHY2SqGw0P3DEjOLuhsLKiIDBhQcNgjWvydTFwY2RvnNKamV9WA0ij0d0CYUmWdcv2p+Fjd+lHOXQ5yQ/gnyNYCmVuZHN0cmVhbQplbmRvYmoKCnhyZWYKMCA3CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAwMDA0MiAwMDAwMCBuIAowMDAwMDAwMTIwIDAwMDAwIG4gCjAwMDAwMDAxNzIgMDAwMDAgbiAKMDAwMDAwMDIxMyAwMDAwMCBuIAowMDAwMDAwMzIwIDAwMDAwIG4gCjAwMDAwMDA0MDkgMDAwMDAgbiAKCnRyYWlsZXIKPDwvU2l6ZSA3L1Jvb3QgMSAwIFIvSURbPEMzOEFDM0FDQzM4NkMyOURDM0FDQzM5RUMzQTU3QUMyPjxERkFEODQyMTZFQTVBNTQ5MTYyOTk2NjBGRjk1ODc2QT5dPj4Kc3RhcnR4cmVmCjYwNwolJUVPRgo="
)
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAPAAAABQCAIAAACoK28rAAAEpUlEQVR42u3dSyh0fxzH8Rn+mTHlUk8mipLZiTChlBmSy0RhoqRGiY1s7JDIynXBApG1XDZsKNkNFsPCQkRuuURZyGDcR7//4vTX5DzOzOP/mDyP92t15pzfz+/SZ76OzGnUQggV8LcIYAtAoAECDRBogECDQAMEGiDQAIEGCDQINECgAQINEGiAQINAAwQaINAAgQbe84/yZbVazR7hq1F4EJYKje9Uob2+IQB/8nrLQIUGfxQCBBog0ACBBoEGCDRAoAECDRBoEGiAQAMEGvgDA63T6bKzs7OysoxGo91u/7yBuru7PzAxSV9fn+8dNzc3h4eHpePw8HA/78avLlP1PT8rrcCXNgrCwsKkg/X19cTERPFpXgf6pPa/d9AP78ZvmfYfzWsg/XTLkZCQcHp6enl5abPZcnNzzWbz6uqqSqU6Pz8vLi42mUzV1dWvBc+z8knH8o4DAwMpKSlGo3FhYaG9vd3lcuXn58vHXVpa8nGG4eHhNTU1BoNhZGTEZrPFxcX19/dLJTkzMzMhIUF66Uth9jroe7vhuSj5VYVlwt8Ven5+vry8vLa21uFwCCGOjo6SkpKEEDabbWxsTAgxMzOj0WjkdUg6lneMiIi4vr7e2tqqqqpSKF0tLS02m21nZ8drqdNoNA6H4+joSK1Wr6ysHB4eRkVFCSHq6uoWFxcvLi6kl559Pzzoe7vhuSj5VSq0L4FUKz+NIj0g8OEnVnQ6XXp6+vPz8/b29ubmZlpamsFgkC6dnp5ub2/Hxsbu7e1pNBq32x0WFnZ7eyuVQKfTKTULDQ29vr6OiYl507G2tvbq6qq+vj4vL+9Nl9bW1uXl5YaGBqvVqlKpzs7OOjo6NBqN572yNDHpuKurKyMjQ6fT3dzcBAYGarXau7u7gIAA6Wfe3NxMTk7u7e0NDQ25XC7PsT42qMJueC5KvuTAwEDPEVXf+IkVpUD6p0L39PR0dXVFRkbe398LIV5eXux2uxBCr9c/PDwIIR4fH4ODg6XGISEh0sHl5aVUtuUdhRB2u91qtVZXVyuXrqenp8HBwYqKCuUKLa+70kFBQcHo6OjJycnrrLxWaK+Dvrcbnov66VUqtNdA+inQa2trVqu1rKxsfHxcCDE7O2uxWIQQpaWlU1NTQojJyUmtVis1jo6O3tjYEEIMDg5KJ990dDqdZrP56enJ5XLp9XrpPfDy8iKfwMTERElJydzcnNdbjvcC/ePHD6fTubu7GxQU5GOgvQ760914syj5Xiksk0D7O9C3t7cGg+Hw8NBisZjN5pycnP39fSHEwcGByWQymUxNTU2vjaenp+Pj47OzsxsbG6WTx8fHbzr29vYajcbk5OSBgQEhRGFhYVFRkXwCo6Ojbrdbfj44ODjrP83NzQqBbmtri4+Pr6ysfP1l8togNTW1s7PT90G97obnouRLVlgmgfbTPfQv4QYR//8emv8U4u9K/Nep0AAVGiDQINAAgQYINECgAQINAg0QaIBAAwQaBJotgOq7fWkQX+4GKjSg+nIfHwWo0ACBBgg0QKBBoAECDRBogEADBBoEGiDQAIEGCDRAoEGgAQINEGiAQOM7+xfngDgsqXJQ7AAAAABJRU5ErkJggg=="
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
        "fileSize": len(_PDF_BYTES),
        "version": {"number": 1},
        "downloadLink": "/download/reset-policy.pdf",
    },
    {
        "id": "att-2",
        "status": "current",
        "title": "flow-diagram.png",
        "pageId": SEEDED_PAGE_ID,
        "mediaType": "image/png",
        "fileSize": len(_PNG_BYTES),
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
        "results": [{key: value for key, value in _SEEDED_PAGE.items() if key not in ("body",)}],
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
    _recorded["attachment_listings"].append({"page_id": page_id, "filename": request.query_params.get("filename")})
    if page_id != SEEDED_PAGE_ID:
        return {"results": [], "_links": {"next": None}}
    return {"results": _SEEDED_ATTACHMENTS, "_links": {"next": None}}


@app.get("/wiki/download/{filename}")
async def download_attachment(filename: str) -> Response:
    _recorded["attachment_downloads"].append({"filename": filename})
    if filename == "reset-policy.pdf":
        return Response(content=_PDF_BYTES, media_type="application/pdf")
    if filename == "flow-diagram.png":
        return Response(content=_PNG_BYTES, media_type="image/png")
    return Response(status_code=404)


@app.get("/__recorded")
async def recorded() -> dict:
    return _recorded

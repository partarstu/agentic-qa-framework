# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Stateful recording mock for the Confluence Cloud REST API v2 surface.

Serves the endpoints ``ConfluenceClient`` exercises: the space lookup by key,
the space page listing (cursor pagination), the single-page fetch with a storage
body and the per-page attachment listing. The space seeds one page with
headings, paragraphs and a container macro; a small PDF and a PNG attachment are
listed already so the ingestion flow sees the full shape.

A second space holds one page, one text attachment whose names ``POST /__control/rename`` changes (for the
smoke test of the rename handling) and one legacy workbook (for the test of its conversion). Like the real API, the attachment listing rejects a ``sort``
value outside the ``AttachmentSortOrder`` enum with a 400.

Everything recorded is exposed at ``GET /__recorded`` for the smoke assertions.
"""

import base64

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

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

RENAME_SPACE_KEY = "RENAMEDOC"
RENAME_SPACE_ID = "9002"
RENAME_PAGE_ID = "7707"
RENAME_PAGE_TITLE = "Rename Candidate"
RENAME_ATTACHMENT_NAME = "notes.txt"
_NOTES_BYTES = b"Notes that outlive every rename."
RENAME_LEGACY_SHEET_NAME = "limits.xls"
# A legacy workbook with two sheets in default-width columns, made with LibreOffice: a PDF conversion would clip the cell texts.
_LIMITS_XLS_BYTES = base64.b64decode(
    "0M8R4KGxGuEAAAAAAAAAAAAAAAAAAAAAOwADAP7/CQAGAAAAAAAAAAAAAAABAAAACQAAAAAAAAAAEAAAAgAAAAEAAAD+////AAAA"
    "AAAAAAD/////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "///////////////////////////////////////////////////////////////////////////////////9//////////7///8E"
    "AAAABQAAAAYAAAAHAAAACAAAAP7///8KAAAA/v//////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "/////////////////////////////////////////////////////////////////1IAbwBvAHQAIABFAG4AdAByAHkAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWAAUA////////////////AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAA/v///wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAD///////////////8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD+////AAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP//"
    "/////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP7///8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA////////////////AAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/v///wAAAAAAAAAAAQAAAAIAAAADAAAABAAAAAUAAAAGAAAABwAAAAgAAAAJAAAACgAA"
    "AAsAAAAMAAAADQAAAA4AAAAPAAAAEAAAABEAAAASAAAAEwAAABQAAAAVAAAAFgAAABcAAAAYAAAAGQAAABoAAAAbAAAAHAAAAB0A"
    "AAAeAAAAHwAAACAAAAAhAAAA/v///yMAAAD+/////v///yYAAAAnAAAAKAAAAP7///8qAAAAKwAAAP7/////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////"
    "//////////////////////////////8JCBAAAAYFALsNzAcAAAAABgAAAOEAAgCwBMEAAgAAAOIAAABcAHAABAAAQ2FsYyAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIEIAAgCwBGEBAgAAAMABAAA9AQQAAQACAJwAAgAOAK8BAgAAALwBAgAAAD0AEgAAAAAA"
    "AEAAIDgAAAAAAAEAWAJAAAIAAACNAAIAAAAiAAIAAAAOAAIAAQC3AQIAAADaAAIAAAAxAB4A3AAAAAgAkAEAAAACAQAHAUMAYQBs"
    "AGkAYgByAGkAMQAaAMgAAAD/f5ABAAAAAAAABQFBAHIAaQBhAGwAMQAaAMgAAAD/f5ABAAAAAAAABQFBAHIAaQBhAGwAMQAaAMgA"
    "AAD/f5ABAAAAAAAABQFBAHIAaQBhAGwAHgQMAKQABwAAR2VuZXJhbOAAFAAAAKQA9f8gAAAAAAAAAAAAAADAIOAAFAABAAAA9f8g"
    "AAD0AAAAAAAAAADAIOAAFAABAAAA9f8gAAD0AAAAAAAAAADAIOAAFAACAAAA9f8gAAD0AAAAAAAAAADAIOAAFAACAAAA9f8gAAD0"
    "AAAAAAAAAADAIOAAFAAAAAAA9f8gAAD0AAAAAAAAAADAIOAAFAAAAAAA9f8gAAD0AAAAAAAAAADAIOAAFAAAAAAA9f8gAAD0AAAA"
    "AAAAAADAIOAAFAAAAAAA9f8gAAD0AAAAAAAAAADAIOAAFAAAAAAA9f8gAAD0AAAAAAAAAADAIOAAFAAAAAAA9f8gAAD0AAAAAAAA"
    "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"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABIAAgADAAAA//////////8AAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAiAAAASQAAAAAAAAABAE8AbABlAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAACgACAP///////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACQAAAAU"
    "AAAAAAAAAAUAUwB1AG0AbQBhAHIAeQBJAG4AZgBvAHIAbQBhAHQAaQBvAG4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAoAAIA"
    "/////wUAAAD/////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAJQAAAMgAAAAAAAAABQBEAG8AYwB1AG0AZQBu"
    "AHQAUwB1AG0AbQBhAHIAeQBJAG4AZgBvAHIAbQBhAHQAaQBvAG4AAAAAAAAAAAAAADgAAgD///////////////8AAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAApAAAAqAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP///////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAP7///8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAA////////////////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/v///wAAAAAAAAAA"
)

_RENAME_PAGE = {
    "id": RENAME_PAGE_ID,
    "status": "current",
    "title": RENAME_PAGE_TITLE,
    "spaceId": RENAME_SPACE_ID,
    "parentId": None,
    "version": {"createdAt": "2026-09-01T10:00:00Z", "number": 1},
    "body": {"storage": {"representation": "storage", "value": "<h2>Section</h2><p>Stable page text.</p>"}},
    "_links": {"webui": f"/spaces/{RENAME_SPACE_KEY}/pages/{RENAME_PAGE_ID}/{RENAME_PAGE_TITLE.replace(' ', '+')}"},
}
_RENAME_ATTACHMENTS = [
    {
        "id": "att-3",
        "status": "current",
        "title": RENAME_ATTACHMENT_NAME,
        "pageId": RENAME_PAGE_ID,
        "mediaType": "text/plain",
        "fileSize": len(_NOTES_BYTES),
        "version": {"number": 1},
        "downloadLink": f"/download/{RENAME_ATTACHMENT_NAME}",
    },
    {
        "id": "att-4",
        "status": "current",
        "title": RENAME_LEGACY_SHEET_NAME,
        "pageId": RENAME_PAGE_ID,
        "mediaType": "application/vnd.ms-excel",
        "fileSize": len(_LIMITS_XLS_BYTES),
        "version": {"number": 1},
        "downloadLink": f"/download/{RENAME_LEGACY_SHEET_NAME}",
    },
]
_SPACES = {SEEDED_SPACE_KEY: SEEDED_SPACE_ID, RENAME_SPACE_KEY: RENAME_SPACE_ID}
_PAGES = {SEEDED_PAGE_ID: _SEEDED_PAGE, RENAME_PAGE_ID: _RENAME_PAGE}
_ATTACHMENTS = {SEEDED_PAGE_ID: _SEEDED_ATTACHMENTS, RENAME_PAGE_ID: _RENAME_ATTACHMENTS}
# The values of the v2 API's AttachmentSortOrder enum.
_ATTACHMENT_SORT_ORDERS = {"created-date", "-created-date", "modified-date", "-modified-date"}

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
    results = [{"id": _SPACES[key], "key": key, "name": key} for key in keys if key in _SPACES]
    return {"results": results, "_links": {"next": None}}


@app.get("/wiki/api/v2/spaces/{space_id}/pages")
async def list_pages(space_id: str, request: Request) -> dict:
    _recorded["page_listings"].append({"space_id": space_id, "cursor": request.query_params.get("cursor")})
    pages = [page for page in _PAGES.values() if page["spaceId"] == space_id]
    return {
        "results": [{key: value for key, value in page.items() if key != "body"} for page in pages],
        "_links": {"next": None},
    }


@app.get("/wiki/api/v2/pages/{page_id}")
async def get_page(page_id: str, request: Request) -> dict:
    _recorded["page_fetches"].append({"page_id": page_id, "body_format": request.query_params.get("body-format")})
    return _PAGES.get(page_id) or {"message": f"No page with id {page_id}"}


@app.get("/wiki/api/v2/pages/{page_id}/attachments", response_model=None)
async def list_attachments(page_id: str, request: Request):
    sort = request.query_params.get("sort")
    _recorded["attachment_listings"].append(
        {"page_id": page_id, "filename": request.query_params.get("filename"), "sort": sort}
    )
    if sort is not None and sort not in _ATTACHMENT_SORT_ORDERS:
        return JSONResponse(
            status_code=400,
            content={
                "errors": [
                    {
                        "status": 400,
                        "code": "INVALID_REQUEST_PARAMETER",
                        "title": f"Provided value {{{sort}}} for 'sort' is not the correct type. "
                        "Expected type is AttachmentSortOrder",
                    }
                ]
            },
        )
    return {"results": _ATTACHMENTS.get(page_id, []), "_links": {"next": None}}


@app.post("/__control/rename")
async def rename(page_title: str | None = None, attachment_name: str | None = None) -> dict:
    """Renames the rename space's page and/or attachment; a page rename is a new version, an attachment rename is not."""
    if page_title:
        _RENAME_PAGE["title"] = page_title
        _RENAME_PAGE["version"] = {**_RENAME_PAGE["version"], "number": _RENAME_PAGE["version"]["number"] + 1}
        _RENAME_PAGE["_links"] = {
            "webui": f"/spaces/{RENAME_SPACE_KEY}/pages/{RENAME_PAGE_ID}/{page_title.replace(' ', '+')}"
        }
    if attachment_name:
        _RENAME_ATTACHMENTS[0]["title"] = attachment_name
    return {"page_title": _RENAME_PAGE["title"], "attachment_name": _RENAME_ATTACHMENTS[0]["title"]}


@app.get("/wiki/download/{filename}")
async def download_attachment(filename: str) -> Response:
    _recorded["attachment_downloads"].append({"filename": filename})
    if filename == "reset-policy.pdf":
        return Response(content=_PDF_BYTES, media_type="application/pdf")
    if filename == "flow-diagram.png":
        return Response(content=_PNG_BYTES, media_type="image/png")
    if filename == RENAME_ATTACHMENT_NAME:
        return Response(content=_NOTES_BYTES, media_type="text/plain")
    if filename == RENAME_LEGACY_SHEET_NAME:
        return Response(content=_LIMITS_XLS_BYTES, media_type="application/vnd.ms-excel")
    return Response(status_code=404)


@app.get("/__recorded")
async def recorded() -> dict:
    return _recorded

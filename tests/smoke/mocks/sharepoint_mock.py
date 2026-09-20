# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Stateful recording mock for the Microsoft Graph surface the SharePoint sync exercises.

Serves the Entra token endpoint (client-credentials flow), the drive delta enumeration
(root folder, one subfolder and one small PDF file, ending in a delta link) and the item
content download. Everything recorded is exposed at ``GET /__recorded`` for the smoke
assertions.
"""

import base64
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="SharePoint Graph Mock")

TENANT_ID = "smoke-tenant"
DRIVE_ID = "drive-smoke"
ROOT_FOLDER_ID = "root-folder"
DOCS_FOLDER_ID = "docs-folder"
PDF_FILE_ID = "file-pdf"
PDF_FILE_NAME = "password-reset-policy.pdf"
DELTA_LINK = f"http://sharepoint_mock:8097/drives/{DRIVE_ID}/root/delta?token=smoke-delta-1"

# The same tiny valid PDF the Confluence mock ships.
_PDF_BYTES = base64.b64decode(
    "JVBERi0xLjcKJcK1wrYKJSBXcml0dGVuIGJ5IE11UERGIDEuMjguMgoKMSAwIG9iago8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFIvSW5mbzw8L1Byb2R1Y2VyKE11UERGIDEuMjguMik+Pj4+CmVuZG9iagoKMiAwIG9iago8PC9UeXBlL1BhZ2VzL0NvdW50IDEvS2lkc1s0IDAgUl0+PgplbmRvYmoKCjMgMCBvYmoKPDwvRm9udDw8L2hlbHYgNSAwIFI+Pj4+CmVuZG9iagoKNCAwIG9iago8PC9UeXBlL1BhZ2UvTWVkaWFCb3hbMCAwIDU5NSA4NDJdL1JvdGF0ZSAwL1Jlc291cmNlcyAzIDAgUi9QYXJlbnQgMiAwIFIvQ29udGVudHNbNiAwIFJdPj4KZW5kb2JqCgo1IDAgb2JqCjw8L1R5cGUvRm9udC9TdWJ0eXBlL1R5cGUxL0Jhc2VGb250L0hlbHZldGljYS9FbmNvZGluZy9XaW5BbnNpRW5jb2Rpbmc+PgplbmRvYmoKCjYgMCBvYmoKPDwvTGVuZ3RoIDEyOS9GaWx0ZXIvRmxhdGVEZWNvZGU+PgpzdHJlYW0KeNodjLEKAkEMRPt8Rf7AbLI7cwdiIdjYCduJhXorFlrY+P3mJAwMj3mRj+y7FLW8onQlTftbNs/x+mop2h963jZHY2SqGw0P3DEjOLuhsLKiIDBhQcNgjWvydTFwY2RvnNKamV9WA0ij0d0CYUmWdcv2p+Fjd+lHOXQ5yQ/gnyNYCmVuZHN0cmVhbQplbmRvYmoKCnhyZWYKMCA3CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAwMDA0MiAwMDAwMCBuIAowMDAwMDAwMTIwIDAwMDAwIG4gCjAwMDAwMDAxNzIgMDAwMDAgbiAKMDAwMDAwMDIxMyAwMDAwMCBuIAowMDAwMDAwMzIwIDAwMDAwIG4gCjAwMDAwMDA0MDkgMDAwMDAgbiAKCnRyYWlsZXIKPDwvU2l6ZSA3L1Jvb3QgMSAwIFIvSURbPEMzOEFDM0FDQzM4NkMyOURDM0FDQzM5RUMzQTU3QUMyPjxERkFEODQyMTZFQTVBNTQ5MTYyOTk2NjBGRjk1ODc2QT5dPj4Kc3RhcnR4cmVmCjYwNwolJUVPRgo="
)

_recorded: dict[str, list] = {"token_requests": [], "delta_calls": [], "downloads": []}


def _folder(item_id: str, name: str, parent_id: str | None) -> dict:
    parent = {"id": parent_id, "driveId": DRIVE_ID} if parent_id else {"driveId": DRIVE_ID}
    return {"id": item_id, "name": name, "folder": {"childCount": 0}, "parentReference": parent}


def _pdf_file() -> dict:
    return {
        "id": PDF_FILE_ID,
        "name": PDF_FILE_NAME,
        "file": {"mimeType": "application/pdf"},
        "size": len(_PDF_BYTES),
        "cTag": f"c:{{{PDF_FILE_ID}}},1",
        "eTag": f'"{{{PDF_FILE_ID}}},1"',
        "parentReference": {"id": DOCS_FOLDER_ID, "driveId": DRIVE_ID},
    }


@app.post("/{tenant_id}/oauth2/v2.0/token")
async def token(tenant_id: str, request: Request) -> JSONResponse:
    form = dict((await request.form()).items())
    _recorded["token_requests"].append(
        {"tenant": tenant_id, "grant_type": form.get("grant_type"), "scope": form.get("scope")}
    )
    return JSONResponse(
        {
            "access_token": "smoke-graph-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
    )


@app.get("/drives/{drive_id}/root/delta")
async def delta(drive_id: str) -> JSONResponse:
    _recorded["delta_calls"].append({"drive_id": drive_id, "at": time.time()})
    return JSONResponse(
        {
            "value": [_folder(ROOT_FOLDER_ID, "", None), _folder(DOCS_FOLDER_ID, "Docs", ROOT_FOLDER_ID), _pdf_file()],
            "@odata.deltaLink": _recorded.get("next_delta_link") or DELTA_LINK,
        }
    )


@app.post("/__hand_out_delta_link")
async def hand_out_delta_link(request: Request) -> JSONResponse:
    """Makes the next enumeration store the given delta link (the credential-scope control's input).

    The delta link is response data the sync persists and later requests with the Graph
    bearer token attached, so the suite uses this to hand out one on another origin.
    """
    body = await request.json()
    _recorded["next_delta_link"] = body.get("delta_link")
    return JSONResponse({"delta_link": _recorded["next_delta_link"]})


@app.get("/drives/{drive_id}/items/{item_id}/content")
async def download(drive_id: str, item_id: str) -> Response:
    _recorded["downloads"].append({"drive_id": drive_id, "item_id": item_id, "at": time.time()})
    return Response(content=_PDF_BYTES, media_type="application/pdf")


@app.get("/__recorded")
async def recorded() -> JSONResponse:
    return JSONResponse(_recorded)

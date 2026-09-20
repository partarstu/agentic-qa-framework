# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Local sync service: the same two scopes over HTTP for development.

Runs the sync inline and returns the result. It mutates the vector database, so it
requires the internal-service API key like the other internal services.

Each handler imports its runner inside the function: a runner constructs vector-database
clients, so importing all four at module level would build them for every startup whatever
the request asks for.
"""

import argparse
import hmac
import os
import sys

# Make the runtime importable when the service is started directly. The image copies rag_sync/ next to
# common/, while the repository nests it under services/, so both the package's parent directory
# (for "rag_sync.*") and the one above it (the repository root, for "common.*") go on the path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

import config
from common import utils
from common.models import ConfluenceSyncRequest as SharedConfluenceSyncRequest
from common.models import JiraSyncRequest as SharedJiraSyncRequest
from common.models import SharePointSyncRequest as SharedSharePointSyncRequest
from common.services.sync_lock_store import SyncLockHeldError
from common.utils import compile_name_pattern

logger = utils.get_logger("rag_sync_local_service")

app = FastAPI(title="RAG Sync Local Service")


@app.get("/health")
def health_check():
    """Liveness for container healthchecks; no auth, no work."""
    return {"status": "ok"}


def _require_service_auth(x_api_key: str | None = Header(default=None)) -> None:
    """The local sync service mutates the vector DB, so it requires the internal key."""
    expected = config.INTERNAL_SERVICE_API_KEY
    if not expected:
        raise HTTPException(status_code=503, detail="INTERNAL_SERVICE_API_KEY is not configured.")
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _validate_name_pattern(pattern: str | None) -> None:
    """Rejects an unusable name pattern as a bad request, the way the orchestrator does.

    Raises:
        HTTPException: 422 when the pattern cannot be compiled.
    """
    if not pattern:
        return
    try:
        compile_name_pattern(pattern)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


# The scopes are the orchestrator's validated ones (the constraints guarding JQL and the REST
# paths live there, once); this service only adds the holder token the orchestrator issues.
class _LockedSyncRequest(BaseModel):
    lock_token: str | None = Field(default=None, description="Holder token issued by the orchestrator, if any.")


class JiraSyncRequest(SharedJiraSyncRequest, _LockedSyncRequest):
    pass


class SharePointSyncRequest(SharedSharePointSyncRequest, _LockedSyncRequest):
    pass


class ConfluenceSyncRequest(SharedConfluenceSyncRequest, _LockedSyncRequest):
    pass


@app.post("/sync/jira")
async def sync_jira(request: JiraSyncRequest, _: None = Depends(_require_service_auth)):
    """Runs the Jira sync inline and returns the result."""
    from rag_sync.jira_sync import JiraRagSyncRunner
    from rag_sync.outcome_reporting import report_terminal_outcome

    try:
        result = await JiraRagSyncRunner().sync_project(request.project_key, lock_token=request.lock_token)
    except SyncLockHeldError as e:
        await report_terminal_outcome("jira", request.project_key, error=e)
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as exc:
        await report_terminal_outcome("jira", request.project_key, error=exc)
        raise
    await report_terminal_outcome("jira", request.project_key, result=result)
    return {"message": "Jira sync completed.", "details": result.model_dump()}


@app.post("/sync/test_cases")
async def sync_test_cases(request: JiraSyncRequest, _: None = Depends(_require_service_auth)):
    """Runs the test-case full resync inline and returns the result."""
    from rag_sync.outcome_reporting import report_terminal_outcome
    from rag_sync.test_case_sync import TestCaseRagSyncRunner

    try:
        result = await TestCaseRagSyncRunner().sync_project(request.project_key, lock_token=request.lock_token)
    except SyncLockHeldError as e:
        await report_terminal_outcome("test_cases", request.project_key, error=e)
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as exc:
        await report_terminal_outcome("test_cases", request.project_key, error=exc)
        raise
    await report_terminal_outcome("test_cases", request.project_key, result=result)
    return {"message": f"Test-case sync {result.status}.", "details": result.model_dump()}


@app.post("/sync/sharepoint")
async def sync_sharepoint(request: SharePointSyncRequest, _: None = Depends(_require_service_auth)):
    """Runs the SharePoint sync inline and returns the result."""
    from rag_sync.outcome_reporting import report_terminal_outcome
    from rag_sync.sharepoint_sync import SharePointRagSyncRunner

    _validate_name_pattern(request.attachment_name_pattern)
    try:
        result = await SharePointRagSyncRunner().sync_drive(
            drive_id=request.drive_id,
            folder_path=request.folder_path,
            file_name_pattern=request.attachment_name_pattern,
            lock_token=request.lock_token,
        )
    except SyncLockHeldError as e:
        await report_terminal_outcome("sharepoint", request.drive_id, error=e)
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as exc:
        await report_terminal_outcome("sharepoint", request.drive_id, error=exc)
        raise
    await report_terminal_outcome("sharepoint", request.drive_id, result=result)
    return {"message": f"SharePoint sync {result.status}.", "details": result.model_dump()}


@app.post("/sync/confluence")
async def sync_confluence(request: ConfluenceSyncRequest, _: None = Depends(_require_service_auth)):
    """Runs the Confluence sync inline and returns the result."""
    from rag_sync.confluence_sync import ConfluenceRagSyncRunner
    from rag_sync.outcome_reporting import report_terminal_outcome

    _validate_name_pattern(request.attachment_name_pattern)
    try:
        result = await ConfluenceRagSyncRunner().sync_space(
            space_key=request.space_key,
            page_id=str(request.page_id) if request.page_id else None,
            attachment_name_pattern=request.attachment_name_pattern,
            skip_page_body=request.skip_page_body,
            lock_token=request.lock_token,
        )
    except SyncLockHeldError as e:
        await report_terminal_outcome("confluence", request.space_key, error=e)
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as exc:
        await report_terminal_outcome("confluence", request.space_key, error=exc)
        raise
    await report_terminal_outcome("confluence", request.space_key, result=result)
    return {"message": f"Confluence sync {result.status}.", "details": result.model_dump()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local RAG sync service.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8080)))
    args = parser.parse_args()
    uvicorn.run(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()

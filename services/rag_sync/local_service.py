# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Local sync service: the same two scopes over HTTP for development (WS8).

Runs the sync inline and returns the result. It mutates the vector database, so it
requires the internal-service API key like the other internal services.
"""

import argparse
import hmac
import os
import sys

# Make the repository root importable when the service is started directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

import config
from common import utils

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


class JiraSyncRequest(BaseModel):
    project_key: str = Field(min_length=1, description="The Jira project key to synchronize.")


class ConfluenceSyncRequest(BaseModel):
    space_key: str = Field(min_length=1, description="The Confluence space key (may start with '~').")
    page_id: int | None = Field(default=None, description="Restrict the sync to one page of the space.")
    attachment_name_pattern: str | None = Field(
        default=None, description="Regex filtering attachment file names, compiled case-insensitively."
    )
    skip_page_body: bool = Field(default=False, description="Ingest attachments only.")
    lock_token: str | None = Field(default=None, description="Holder token issued by the orchestrator, if any.")


@app.post("/sync/jira")
async def sync_jira(request: JiraSyncRequest, _: None = Depends(_require_service_auth)):
    """Runs the Jira sync inline and returns the result."""
    from rag_sync.jira_sync import JiraRagSyncRunner

    result = await JiraRagSyncRunner().sync_project(request.project_key)
    return {"message": "Jira sync completed.", "details": result.model_dump()}


@app.post("/sync/confluence")
async def sync_confluence(request: ConfluenceSyncRequest, _: None = Depends(_require_service_auth)):
    """Runs the Confluence sync inline (ships with the document RAG ingestion)."""
    from common.utils import compile_name_pattern

    if request.attachment_name_pattern:
        compile_name_pattern(request.attachment_name_pattern)
    raise HTTPException(status_code=501, detail="The Confluence sync is not implemented yet.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local RAG sync service.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8080)))
    args = parser.parse_args()
    uvicorn.run(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()

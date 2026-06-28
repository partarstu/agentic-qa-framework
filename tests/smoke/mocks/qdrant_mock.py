# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Minimal mock for the Qdrant REST surface the incident-creation agent touches.

The agent only ever *searches* the vector DB for duplicate candidates, and
``VectorDbService.search`` first checks whether the collection exists (via
``GET /collections``) and returns no hits — without embedding anything — when it
does not. Reporting an empty collection list is therefore enough to drive the
"no duplicates -> create a fresh bug" path with no embedding service involved.

``GET /`` answers the qdrant-client's version-compatibility probe.
"""

from fastapi import FastAPI

app = FastAPI()


@app.get("/")
async def root() -> dict:
    """Answer the qdrant-client version-compatibility probe."""
    return {"title": "qdrant - vector search engine", "version": "1.12.4", "commit": "smoke-mock"}


@app.get("/collections")
async def list_collections() -> dict:
    """Report no collections, so VectorDbService.search short-circuits to no hits."""
    return {"result": {"collections": []}, "status": "ok", "time": 0.0}

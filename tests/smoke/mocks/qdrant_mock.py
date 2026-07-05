# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Stateful recording mock for the Qdrant REST surface, plus the embedding service.

Serves the endpoints ``VectorDbService`` exercises: the collection list/create
cycle, point upsert/retrieve/scroll/delete and similarity queries. The RAG sync
flow (``/update-rag-db``) creates its collections and upserts the seeded story
here; the incident-creation agent's duplicate search probes the collection list
and, when the collection exists, queries it (always answered with no hits, so the
"no duplicates -> create a fresh bug" path is taken deterministically).

``POST /embed`` stands in for the embedding service — ``VectorDbService`` embeds
every text before storing or querying, and the vector values themselves are
irrelevant here — so the whole flow stays hermetic and LLM-free.

``GET /`` answers the qdrant-client's version-compatibility probe, and everything
recorded is exposed at ``GET /__recorded`` for the smoke assertions.
"""

from fastapi import FastAPI, Request

app = FastAPI()

_EMBEDDING_DIM = 8

# Collections keyed by name; each holds its points keyed by stringified point id.
_collections: dict[str, dict[str, dict]] = {}
_recorded: dict = {
    "collections_probes": 0,
    "created_collections": [],
    "upserted_points": [],
    "queries": [],
    "deleted_point_ids": [],
}

_UPDATE_RESULT = {"result": {"operation_id": 0, "status": "completed"}, "status": "ok", "time": 0.0}


@app.get("/")
async def root() -> dict:
    """Answer the qdrant-client version-compatibility probe."""
    return {"title": "qdrant - vector search engine", "version": "1.16.2", "commit": "smoke-mock"}


@app.post("/embed")
async def embed(request: Request) -> dict:
    """Deterministic stand-in for the embedding service; only the dimension matters."""
    await request.json()
    return {"embedding": [0.1] * _EMBEDDING_DIM}


@app.get("/collections")
async def list_collections() -> dict:
    _recorded["collections_probes"] += 1
    names = [{"name": name} for name in _collections]
    return {"result": {"collections": names}, "status": "ok", "time": 0.0}


@app.put("/collections/{name}")
async def create_collection(name: str, request: Request) -> dict:
    await request.json()
    _collections.setdefault(name, {})
    _recorded["created_collections"].append(name)
    return {"result": True, "status": "ok", "time": 0.0}


@app.put("/collections/{name}/points")
async def upsert_points(name: str, request: Request) -> dict:
    payload = await request.json()
    points = _collections.setdefault(name, {})
    for point in payload.get("points", []):
        points[str(point["id"])] = point
        _recorded["upserted_points"].append(
            {"collection": name, "id": point["id"], "payload": point.get("payload", {})}
        )
    return _UPDATE_RESULT


@app.post("/collections/{name}/points")
async def retrieve_points(name: str, request: Request) -> dict:
    payload = await request.json()
    points = _collections.get(name, {})
    records = [
        {"id": points[str(pid)]["id"], "payload": points[str(pid)].get("payload"), "vector": None}
        for pid in payload.get("ids", [])
        if str(pid) in points
    ]
    return {"result": records, "status": "ok", "time": 0.0}


@app.post("/collections/{name}/points/scroll")
async def scroll_points(name: str, request: Request) -> dict:
    """Return every stored point id; the suite only ever stores one project's issues."""
    await request.json()
    records = [{"id": point["id"], "payload": None, "vector": None} for point in _collections.get(name, {}).values()]
    return {"result": {"points": records, "next_page_offset": None}, "status": "ok", "time": 0.0}


@app.post("/collections/{name}/points/delete")
async def delete_points(name: str, request: Request) -> dict:
    payload = await request.json()
    points = _collections.get(name, {})
    for pid in payload.get("points", []):
        points.pop(str(pid), None)
        _recorded["deleted_point_ids"].append({"collection": name, "id": pid})
    return _UPDATE_RESULT


@app.post("/collections/{name}/points/query")
async def query_points(name: str, request: Request) -> dict:
    """Always report no hits, so the duplicate search deterministically finds no duplicates."""
    payload = await request.json()
    _recorded["queries"].append({"collection": name, "filter": payload.get("filter")})
    return {"result": {"points": []}, "status": "ok", "time": 0.0}


@app.get("/__recorded")
async def recorded() -> dict:
    return _recorded

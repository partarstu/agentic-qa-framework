# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Stateful recording mock for the Qdrant REST surface, plus the embedding service.

Serves the endpoints ``VectorDbService`` exercises: the collection list/create
cycle, point upsert/retrieve/scroll/delete and similarity queries. The RAG sync
flow (``/update-jira-db``, forwarded to the local sync service) creates its collections and upserts the seeded story
here; the incident-creation agent's duplicate search probes the collection list
and, when the collection exists, queries it (always answered with no hits, so the
"no duplicates -> create a fresh bug" path is taken deterministically).

``POST /embed-document-text``, ``POST /embed-query-text``, ``POST /embed-page-image`` and
``POST /embed-visual-query-text`` stand in for the embedding service —
``VectorDbService`` embeds every text and (in visual mode) every attachment page
image before storing or querying, and the vector values themselves are irrelevant
here — so the whole flow stays hermetic and LLM-free.

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
    "embedding_calls": [],
    "hybrid_queries": [],
}

_UPDATE_RESULT = {"result": {"operation_id": 0, "status": "completed"}, "status": "ok", "time": 0.0}


@app.get("/")
async def root() -> dict:
    """Answer the qdrant-client version-compatibility probe."""
    return {"title": "qdrant - vector search engine", "version": "1.16.2", "commit": "smoke-mock"}


@app.post("/embed-document-text")
async def embed_document_text(request: Request) -> dict:
    """Deterministic stand-in for the embedding service; only the dimension matters."""
    payload = await request.json()
    texts = payload.get("texts", [])
    _recorded["embedding_calls"].append({"endpoint": "/embed-document-text", "texts": texts})
    return _embeddings_response(texts)


@app.post("/embed-query-text")
async def embed_query_text(request: Request) -> dict:
    """Deterministic stand-in for the embedding service; only the dimension matters."""
    payload = await request.json()
    texts = payload.get("texts", [])
    _recorded["embedding_calls"].append({"endpoint": "/embed-query-text", "texts": texts})
    return _embeddings_response(texts)


@app.post("/embed-page-image")
async def embed_page_image(request: Request) -> dict:
    """Visual-mode stand-in for the embedding service's page-image endpoint.

    Only the base64 images' lengths are recorded (the payloads themselves would bloat
    the recording); the smoke assertions use them to prove real page images arrived.
    """
    payload = await request.json()
    images = payload.get("images", [])
    _recorded["embedding_calls"].append(
        {
            "endpoint": "/embed-page-image",
            "image_count": len(images),
            "image_lengths": [len(image) for image in images],
        }
    )
    return _visual_response(len(images))


@app.post("/embed-visual-query-text")
async def embed_visual_query_text(request: Request) -> dict:
    """Visual-mode stand-in for the embedding service's visual query endpoint."""
    payload = await request.json()
    texts = payload.get("texts", [])
    _recorded["embedding_calls"].append({"endpoint": "/embed-visual-query-text", "texts": texts})
    return _visual_response(len(texts))


def _fake_embedding() -> dict:
    return {"dense": [0.1] * _EMBEDDING_DIM, "sparse": {"indices": [1], "values": [0.5]}}


def _embeddings_response(texts: list) -> dict:
    """The embedding service response shape, including the model identity field."""
    return {"model": "mock-model", "embeddings": [_fake_embedding() for _ in texts]}


def _visual_response(count: int) -> dict:
    """The visual endpoint response shape: one dense visual vector per input."""
    return {"model": "mock-visual-model", "vectors": [[0.2] * _EMBEDDING_DIM for _ in range(count)]}


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
        vector = point.get("vector")
        _recorded["upserted_points"].append(
            {
                "collection": name,
                "id": point["id"],
                "payload": point.get("payload", {}),
                # Named-vector names only; the values are irrelevant in the smoke flow.
                "vector_names": sorted(vector) if isinstance(vector, dict) else [],
            }
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
    """Return stored points honouring top-level ``must`` payload filters.

    The suite scrolls for reconciliation (issue IDs by project) and for the sync
    state (fingerprints by kind + scope), so the payload has to be included and
    the equality filters honoured.
    """
    payload = await request.json()
    must = ((payload.get("filter") or {}).get("must")) or []
    required = {c["key"]: c["match"]["value"] for c in must if "match" in c}
    records = [
        {"id": point["id"], "payload": point.get("payload"), "vector": None}
        for point in _collections.get(name, {}).values()
        if all(point.get("payload", {}).get(key) == value for key, value in required.items())
    ]
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
    """Always report no hits, so the duplicate search deterministically finds no duplicates.

    Hybrid queries (named-vector prefetches fused with RRF) are recorded so the smoke
    suite can assert the incident flow issues a hybrid search.
    """
    payload = await request.json()
    _recorded["queries"].append({"collection": name, "filter": payload.get("filter")})
    prefetches = payload.get("prefetch") or []
    if prefetches:
        _recorded["hybrid_queries"].append(
            {
                "collection": name,
                "prefetches": [
                    {
                        "using": p.get("using"),
                        "limit": p.get("limit"),
                        "score_threshold": p.get("score_threshold"),
                    }
                    for p in prefetches
                ],
                "fusion": (payload.get("query") or {}).get("fusion"),
                "limit": payload.get("limit"),
                "filter": payload.get("filter"),
            }
        )
    return {"result": {"points": []}, "status": "ok", "time": 0.0}


@app.get("/__recorded")
async def recorded() -> dict:
    return _recorded

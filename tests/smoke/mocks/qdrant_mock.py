# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Stateful recording mock for the Qdrant REST surface, plus the embedding service.

Serves the endpoints ``VectorDbService`` exercises: the collection list/create
cycle (recording each collection's named vector schema and payload indexes), point upsert (recording
each point's vector names)/retrieve/scroll, deletion by IDs or by payload filter,
payload-only updates and similarity queries. Like Qdrant, it rejects point IDs that are
neither unsigned integers nor UUIDs with a 400. The RAG sync
flow (``/update-jira-db``, forwarded to the local sync service) creates its collections and upserts the seeded story
here; the incident-creation agent's duplicate search probes the collection list
and, when the collection exists, queries it (always answered with no hits, so the
"no duplicates -> create a fresh bug" path is taken deterministically). Only the
test-case collection answers queries with its stored matching points, so the test-case
review's duplicate judge runs over the test cases indexed next to it.

``POST /embed-document-text`` and ``POST /embed-query-text`` stand in for the
embedding service — ``VectorDbService`` embeds every text before storing or
querying, and the vector values themselves are irrelevant here — so the whole
flow stays hermetic and LLM-free.

``GET /`` answers the qdrant-client's version-compatibility probe, and everything
recorded is exposed at ``GET /__recorded`` for the smoke assertions.
"""

import uuid

from fastapi import FastAPI, HTTPException, Request

app = FastAPI()

_EMBEDDING_DIM = 8

# Collections keyed by name; each holds its points keyed by stringified point id.
_collections: dict[str, dict[str, dict]] = {}
# The vector configuration each collection was created with, keyed by collection name.
_vector_configs: dict[str, dict] = {}
_recorded: dict = {
    "collections_probes": 0,
    "created_collections": [],
    "collection_schemas": {},
    "payload_indexes": [],
    "upserted_points": [],
    "queries": [],
    "deleted_point_ids": [],
    "deleted_by_filter": [],
    "payload_updates": [],
    "embedding_calls": [],
    "hybrid_queries": [],
}

_UPDATE_RESULT = {"result": {"operation_id": 0, "status": "completed"}, "status": "ok", "time": 0.0}


def _is_valid_point_id(point_id: object) -> bool:
    """Qdrant accepts only unsigned integers and UUID strings as point IDs."""
    if isinstance(point_id, int):
        return point_id >= 0
    try:
        uuid.UUID(str(point_id))
    except ValueError:
        return False
    return True


def _reject_invalid_point_ids(point_ids: list) -> None:
    """Answer like Qdrant (400) when any ID is neither an unsigned integer nor a UUID."""
    invalid = [point_id for point_id in point_ids if not _is_valid_point_id(point_id)]
    if invalid:
        raise HTTPException(
            status_code=400, detail=f"Format error in JSON body: unable to parse point ID {invalid[0]!r}"
        )


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


def _fake_embedding() -> dict:
    return {"dense": [0.1] * _EMBEDDING_DIM, "sparse": {"indices": [1], "values": [0.5]}}


def _embeddings_response(texts: list) -> dict:
    """The embedding service response shape, including the model identity field."""
    return {"model": "mock-model", "embeddings": [_fake_embedding() for _ in texts]}


@app.get("/collections")
async def list_collections() -> dict:
    _recorded["collections_probes"] += 1
    names = [{"name": name} for name in _collections]
    return {"result": {"collections": names}, "status": "ok", "time": 0.0}


@app.put("/collections/{name}")
async def create_collection(name: str, request: Request) -> dict:
    payload = await request.json()
    _collections.setdefault(name, {})
    _vector_configs[name] = {
        "vectors": payload.get("vectors") or {},
        "sparse_vectors": payload.get("sparse_vectors") or {},
    }
    _recorded["created_collections"].append(name)
    _recorded["collection_schemas"][name] = {
        "vectors": sorted((payload.get("vectors") or {}).keys()),
        "sparse_vectors": sorted((payload.get("sparse_vectors") or {}).keys()),
    }
    return {"result": True, "status": "ok", "time": 0.0}


@app.get("/collections/{name}")
async def get_collection(name: str) -> dict:
    """Describe a collection with the vector configuration it was created with (WS19 schema validation)."""
    if name not in _collections:
        raise HTTPException(status_code=404, detail=f"Collection `{name}` doesn't exist!")
    info = {
        "status": "green",
        "optimizer_status": "ok",
        "segments_count": 1,
        "config": {
            "params": _vector_configs.get(name, {}),
            "hnsw_config": {"m": 16, "ef_construct": 100, "full_scan_threshold": 10000},
            "optimizer_config": {
                "deleted_threshold": 0.2,
                "vacuum_min_vector_number": 1000,
                "default_segment_number": 0,
                "flush_interval_sec": 5,
            },
        },
        "payload_schema": {},
    }
    return {"result": info, "status": "ok", "time": 0.0}


@app.put("/collections/{name}/index")
async def create_payload_index(name: str, request: Request) -> dict:
    """Create a payload index on one field, as ``ensure_collection`` does for every indexed field."""
    payload = await request.json()
    _recorded["payload_indexes"].append(
        {"collection": name, "field_name": payload.get("field_name"), "field_schema": payload.get("field_schema")}
    )
    return _UPDATE_RESULT


@app.put("/collections/{name}/points")
async def upsert_points(name: str, request: Request) -> dict:
    payload = await request.json()
    _reject_invalid_point_ids([point["id"] for point in payload.get("points", [])])
    points = _collections.setdefault(name, {})
    for point in payload.get("points", []):
        points[str(point["id"])] = point
        _recorded["upserted_points"].append(
            {
                "collection": name,
                "id": point["id"],
                "payload": point.get("payload", {}),
                "vector_names": sorted((point.get("vector") or {}).keys()),
            }
        )
    return _UPDATE_RESULT


@app.post("/collections/{name}/points")
async def retrieve_points(name: str, request: Request) -> dict:
    payload = await request.json()
    _reject_invalid_point_ids(payload.get("ids", []))
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
    records = [
        {"id": point["id"], "payload": point.get("payload"), "vector": None}
        for point in _collections.get(name, {}).values()
        if _matches_filter(point, payload.get("filter"))
    ]
    return {"result": {"points": records, "next_page_offset": None}, "status": "ok", "time": 0.0}


@app.post("/collections/{name}/points/delete")
async def delete_points(name: str, request: Request) -> dict:
    """Delete points by IDs or by a payload filter (scope deletion)."""
    payload = await request.json()
    _reject_invalid_point_ids(payload.get("points", []))
    points = _collections.get(name, {})
    if payload.get("filter") is not None:
        _recorded["deleted_by_filter"].append({"collection": name, "filter": payload["filter"]})
        for pid in [pid for pid, point in points.items() if _matches_filter(point, payload["filter"])]:
            points.pop(pid)
    for pid in payload.get("points", []):
        points.pop(str(pid), None)
        _recorded["deleted_point_ids"].append({"collection": name, "id": pid})
    return _UPDATE_RESULT


@app.post("/collections/{name}/points/payload")
async def set_payload(name: str, request: Request) -> dict:
    """Merge a payload into points selected by IDs or by a payload filter, without re-embedding."""
    payload = await request.json()
    _reject_invalid_point_ids(payload.get("points") or [])
    points = _collections.get(name, {})
    _recorded["payload_updates"].append(
        {
            "collection": name,
            "payload": payload.get("payload"),
            "points": payload.get("points"),
            "filter": payload.get("filter"),
        }
    )
    selected_ids = {str(pid) for pid in payload.get("points") or []}
    for pid, point in points.items():
        if pid in selected_ids or (payload.get("filter") is not None and _matches_filter(point, payload["filter"])):
            point.setdefault("payload", {}).update(payload.get("payload") or {})
    return _UPDATE_RESULT


def _equality_conditions(conditions: list[dict] | None) -> dict:
    return {
        condition["key"]: condition["match"]["value"]
        for condition in conditions or []
        if "value" in condition.get("match", {})
    }


def _matches_filter(point: dict, point_filter: dict | None) -> bool:
    """Honour the top-level ``must`` and ``must_not`` equality conditions the services send."""
    payload = point.get("payload", {})
    required = _equality_conditions((point_filter or {}).get("must"))
    excluded = _equality_conditions((point_filter or {}).get("must_not"))
    return all(payload.get(key) == value for key, value in required.items()) and not any(
        payload.get(key) == value for key, value in excluded.items()
    )


# The one collection whose queries are answered with stored points: the test-case review's
# duplicate search, so its judge runs end to end over the test cases indexed next to it.
_ANSWERED_COLLECTION = "test_cases"


def _scored_points(name: str, point_filter: dict | None, limit: int) -> list[dict]:
    if name != _ANSWERED_COLLECTION:
        return []
    matches = [point for point in _collections.get(name, {}).values() if _matches_filter(point, point_filter)]
    return [
        {"id": point["id"], "version": 0, "score": 0.9, "payload": point.get("payload")} for point in matches[:limit]
    ]


@app.post("/collections/{name}/points/query")
async def query_points(name: str, request: Request) -> dict:
    """Report stored matching points for the test-case collection and no hits elsewhere.

    Every other collection answers with no hits, so e.g. the incident duplicate search
    deterministically finds no duplicates. Hybrid queries (named-vector prefetches fused
    with RRF) are recorded with each prefetch's filter so the smoke suite can assert the
    flows issue scoped hybrid searches.
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
                        "filter": p.get("filter"),
                    }
                    for p in prefetches
                ],
                "fusion": (payload.get("query") or {}).get("fusion"),
                "limit": payload.get("limit"),
                "filter": payload.get("filter"),
            }
        )
    point_filter = prefetches[0].get("filter") if prefetches else payload.get("filter")
    points = _scored_points(name, point_filter, payload.get("limit") or 10)
    return {"result": {"points": points}, "status": "ok", "time": 0.0}


@app.get("/__recorded")
async def recorded() -> dict:
    return _recorded

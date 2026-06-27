# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Stateful recording mock for the Zephyr Scale Cloud REST surface.

Serves only the endpoints the generation, classification and review flows exercise
(``ZephyrClient``): create test case + steps + issue link, status listing, and the
read-modify-write ``GET``/``PUT`` cycle used to add labels, review comments and a
status. The in-memory store is exposed at ``GET /__recorded`` for the assertions.
"""

from fastapi import FastAPI, Request

app = FastAPI()

# Test cases keyed by their Zephyr key. Each value mirrors what ZephyrClient reads back.
_test_cases: dict[str, dict] = {}
_issue_links: list[dict] = []
_counter = 0

_STATUSES = [
    {"id": 1, "name": "Draft", "archived": False},
    {"id": 2, "name": "Approved", "archived": False},
    {"id": 3, "name": "Review Complete", "archived": False},
]
_STATUS_NAMES_BY_ID = {status["id"]: status["name"] for status in _STATUSES}


def _resolve_status(status: dict) -> dict:
    """Surface a human-readable status name.

    A status change PUTs only ``{"id": N}``, so the stored status loses its name;
    look it up from the status catalog for the assertions.
    """
    status_id = status.get("id")
    return {"id": status_id, "name": status.get("name") or _STATUS_NAMES_BY_ID.get(status_id, "")}


@app.post("/testcases")
async def create_test_case(request: Request) -> dict:
    global _counter
    payload = await request.json()
    _counter += 1
    project_key = payload.get("projectKey", "SMOKE")
    key = f"{project_key}-T{_counter}"
    _test_cases[key] = {
        "key": key,
        "id": 1000 + _counter,
        "name": payload.get("name", ""),
        "objective": payload.get("objective", ""),
        "precondition": payload.get("precondition"),
        "labels": [],
        "status": {"id": 1, "name": "Draft"},
        "customFields": {"Review Comments": ""},
        "steps": [],
    }
    return {"key": key, "id": 1000 + _counter}


@app.post("/testcases/{key}/teststeps")
async def add_test_steps(key: str, request: Request) -> dict:
    payload = await request.json()
    steps = [item.get("inline", {}) for item in payload.get("items", [])]
    if key in _test_cases:
        _test_cases[key]["steps"] = steps
    return {}


@app.post("/testcases/{key}/links/issues")
async def link_issue(key: str, request: Request) -> dict:
    payload = await request.json()
    _issue_links.append({"test_case_key": key, "issue_id": payload.get("issueId")})
    return {}


@app.get("/testcases/{key}")
async def get_test_case(key: str) -> dict:
    return _test_cases.get(key, {})


@app.put("/testcases/{key}")
async def update_test_case(key: str, request: Request) -> dict:
    payload = await request.json()
    _test_cases[key] = payload
    return {}


@app.get("/statuses")
async def get_statuses() -> dict:
    return {"values": _STATUSES, "maxResults": 100, "startAt": 0, "total": len(_STATUSES), "isLast": True}


@app.get("/__recorded")
async def recorded() -> dict:
    return {
        "test_cases": [
            {
                "key": tc["key"],
                "name": tc.get("name", ""),
                "steps": tc.get("steps", []),
                "labels": tc.get("labels", []),
                "status": _resolve_status(tc.get("status", {})),
                "review_comments": tc.get("customFields", {}).get("Review Comments", ""),
            }
            for tc in _test_cases.values()
        ],
        "issue_links": _issue_links,
    }

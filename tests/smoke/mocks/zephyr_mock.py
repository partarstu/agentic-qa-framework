# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Stateful recording mock for the Zephyr Scale Cloud REST surface.

Serves the endpoints the generation, classification and review flows exercise
(``ZephyrClient``): create test case + steps + issue link, status listing, and the
read-modify-write ``GET``/``PUT`` cycle used to add labels, review comments and a
status. It also serves the read endpoints (test-case listing, steps, links) and the
test-cycle/test-execution writes the ``/execute-tests`` + incident-creation flow
needs, around a pre-seeded ready-for-execution test case. The generation store,
the recorded test cycles, test executions and execution-issue links are exposed
at ``GET /__recorded`` for the assertions (the seeded executable case is
deliberately excluded from it).
"""

from fastapi import FastAPI, Request

app = FastAPI()

# Test cases keyed by their Zephyr key. Each value mirrors what ZephyrClient reads back.
_test_cases: dict[str, dict] = {}
_issue_links: list[dict] = []
_test_cycles: list[dict] = []
_test_executions: list[dict] = []
_execution_issue_links: list[dict] = []
_counter = 0
_test_execution_counter = 0

# A pre-seeded, ready-for-execution test case for the /execute-tests flow. Kept in
# its own store (and out of /__recorded) so it cannot satisfy the generation-flow
# assertions; it is "Approved" and carries the "automated" label the orchestrator
# selects on.
_EXECUTABLE_TC_KEY = "SMOKE-T100"
_executable_test_cases: dict[str, dict] = {
    _EXECUTABLE_TC_KEY: {
        "key": _EXECUTABLE_TC_KEY,
        "id": 1100,
        "name": "Password reset email is sent for a registered address",
        "objective": "Verify the API queues a reset email when given a registered address.",
        "precondition": "A user account exists for the test email address.",
        "labels": ["automated", "api"],
        "status": {"id": 2, "name": "Approved"},
        "customFields": {"Review Comments": ""},
        "steps": [
            {
                "description": "Send POST /api/password-reset with a registered email address",
                "expectedResult": "HTTP 200 and a password-reset email is queued",
                "testData": "email=registered@example.com",
            }
        ],
    }
}


def _all_test_cases() -> dict[str, dict]:
    """Generation-created cases plus the pre-seeded executable case."""
    return {**_executable_test_cases, **_test_cases}

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


@app.get("/testcases")
async def list_test_cases() -> dict:
    """List all test cases; the client filters by status and label for execution."""
    values = list(_all_test_cases().values())
    return {"values": values, "maxResults": 100, "startAt": 0, "total": len(values), "isLast": True}


@app.get("/testcases/{key}")
async def get_test_case(key: str) -> dict:
    return _all_test_cases().get(key, {})


@app.get("/testcases/{key}/teststeps")
async def get_test_steps(key: str) -> dict:
    steps = _all_test_cases().get(key, {}).get("steps", [])
    values = [{"inline": step} for step in steps]
    return {"values": values, "maxResults": 100, "startAt": 0, "total": len(values), "isLast": True}


@app.get("/testcases/{key}/links")
async def get_test_case_links(key: str) -> dict:
    """No issues are linked to the executable test case, so it yields no duplicate candidates."""
    return {"issues": [], "webLinks": []}


@app.post("/testcycles")
async def create_test_cycle(request: Request) -> dict:
    payload = await request.json()
    project_key = payload.get("projectKey", "SMOKE")
    key = f"{project_key}-C{len(_test_cycles) + 1}"
    _test_cycles.append({"key": key, "projectKey": project_key, "name": payload.get("name", "")})
    return {"key": key, "id": 5000 + len(_test_cycles)}


@app.post("/testexecutions")
async def create_test_execution(request: Request) -> dict:
    global _test_execution_counter
    _test_execution_counter += 1
    execution_id = 6000 + _test_execution_counter
    payload = await request.json()
    _test_executions.append(
        {
            "id": execution_id,
            "projectKey": payload.get("projectKey"),
            "testCaseKey": payload.get("testCaseKey"),
            "testCycleKey": payload.get("testCycleKey"),
            "statusName": payload.get("statusName"),
            "comment": payload.get("comment", ""),
            "testScriptResults": payload.get("testScriptResults", []),
        }
    )
    return {"id": execution_id}


@app.post("/testexecutions/{execution_id}/links/issues")
async def link_issue_to_test_execution(execution_id: int, request: Request) -> dict:
    payload = await request.json()
    _execution_issue_links.append({"execution_id": execution_id, "issue_id": payload.get("issueId")})
    return {}


@app.put("/testcases/{key}")
async def update_test_case(key: str, request: Request) -> dict:
    """Read-modify-write updates on the seeded executable case must stay in its own
    store, so they cannot leak into /__recorded and satisfy the generation-flow
    assertions."""
    payload = await request.json()
    store = _executable_test_cases if key in _executable_test_cases else _test_cases
    store[key] = payload
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
        "test_cycles": _test_cycles,
        "test_executions": _test_executions,
        "execution_issue_links": _execution_issue_links,
    }

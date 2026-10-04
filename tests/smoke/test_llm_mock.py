# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the scripted LLM mock; they need no stack, so they carry no ``smoke`` marker."""

import pytest
from fastapi.testclient import TestClient

from tests.smoke.mocks import llm_mock


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(llm_mock, "_recorded", {"requests": [], "unhandled": []})
    return TestClient(llm_mock.app)


def _request(prompt: str, output_fields: list[str]) -> dict:
    output_schema = {"type": "object", "properties": {output_field: {} for output_field in output_fields}}
    return {
        "model": "smoke-mock",
        "messages": [{"role": "user", "content": prompt}],
        "tools": [{"type": "function", "function": {"name": llm_mock.OUTPUT_TOOL_NAME, "parameters": output_schema}}],
    }


def test_a_call_of_no_known_operation_is_rejected_and_recorded_as_unhandled(client: TestClient) -> None:
    response = client.post("/v1/chat/completions", json=_request("Anything", ["unknown_field"]))

    assert response.status_code == 400
    assert client.get("/__recorded").json()["unhandled"] == [
        {"tools": ["final_result"], "output_fields": ["unknown_field"]}
    ]


def test_a_failing_scripted_answer_is_rejected_and_recorded_as_unhandled(client: TestClient) -> None:
    response = client.post("/v1/chat/completions", json=_request("A prompt without the test case to fix", ["ac_ids"]))

    assert response.status_code == 400
    [unhandled] = client.get("/__recorded").json()["unhandled"]
    assert unhandled["operation"] == "test_case_fixing"
    assert unhandled["error"].startswith("TypeError")

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the scripted LLM mock; they need no stack, so they carry no ``smoke`` marker."""

import json

import pytest
from fastapi.testclient import TestClient

import config
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


ROUTING_TOOLS = ("AgentSelected", "SuitableAgentBusy", "NoSuitableAgent")


def _routing_request(task: str, availability: str | None) -> dict:
    """A routing call over a registry of the requirements review agent (or of none, without availability)."""
    registry = (
        f"- ID: agent-1, Name: {config.RequirementsReviewAgentConfig.OWN_NAME}, Skills: review, "
        f"Availability: {availability}\n"
        if availability
        else ""
    )
    schema = {"type": "object", "properties": {"justification": {}}, "required": ["justification"]}
    return {
        "model": "smoke-mock",
        "messages": [
            {"role": "user", "content": f'Target task description: "{task}".\n\nThe list of all agents:\n{registry}'}
        ],
        "tools": [
            {"type": "function", "function": {"name": f"{llm_mock.OUTPUT_TOOL_NAME}_{name}", "parameters": schema}}
            for name in ROUTING_TOOLS
        ],
    }


def _answered_call(client: TestClient, request: dict) -> dict:
    response = client.post("/v1/chat/completions", json=request)
    assert response.status_code == 200
    [call] = response.json()["choices"][0]["message"]["tool_calls"]
    return {"name": call["function"]["name"], "arguments": json.loads(call["function"]["arguments"])}


def test_a_call_offering_the_agent_selected_tool_is_attributed_to_routing(client: TestClient) -> None:
    _answered_call(client, _routing_request("Review the Jira user story QA-1", "available"))

    [recorded] = client.get("/__recorded").json()["requests"]
    assert recorded["operation"] == "routing"


def test_routing_selects_a_suitable_available_agent_through_its_own_tool(client: TestClient) -> None:
    call = _answered_call(client, _routing_request("Review the Jira user story QA-1", "available"))

    assert call["name"] == "final_result_AgentSelected"
    assert call["arguments"]["agent_id"] == "agent-1"
    assert call["arguments"]["justification"]


def test_routing_reports_a_busy_suitable_agent_through_its_own_tool(client: TestClient) -> None:
    call = _answered_call(client, _routing_request("Review the Jira user story QA-1", "busy"))

    assert call["name"] == "final_result_SuitableAgentBusy"
    assert set(call["arguments"]) == {"justification"}


def test_routing_reports_no_suitable_agent_through_its_own_tool(client: TestClient) -> None:
    call = _answered_call(client, _routing_request("Something no agent can do", "available"))

    assert call["name"] == "final_result_NoSuitableAgent"
    assert set(call["arguments"]) == {"justification"}


def test_the_sampling_and_thinking_fields_and_the_tool_fields_of_a_call_are_recorded(client: TestClient) -> None:
    request = {
        **_request("Anything", ["unknown_field"]),
        "temperature": 0.7,
        "top_p": 0.8,
        "presence_penalty": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    client.post("/v1/chat/completions", json=request)

    [recorded] = client.get("/__recorded").json()["requests"]
    assert recorded["temperature"] == 0.7
    assert recorded["top_p"] == 0.8
    assert recorded["presence_penalty"] == 0.0
    assert recorded["chat_template_kwargs"] == {"enable_thinking": False}
    assert "reasoning_effort" not in recorded
    assert recorded["tool_fields"] == {"final_result": {"properties": ["unknown_field"], "required": []}}


def test_a_call_of_no_known_operation_is_rejected_and_recorded_as_unhandled(client: TestClient) -> None:
    response = client.post("/v1/chat/completions", json=_request("Anything", ["unknown_field"]))

    assert response.status_code == 400
    assert client.get("/__recorded").json()["unhandled"] == [
        {"tools": ["final_result"], "output_fields": ["unknown_field"]}
    ]


def test_a_system_message_after_the_first_message_is_rejected_like_qwen_does(client: TestClient) -> None:
    request = _request("Anything", ["unknown_field"])
    request["messages"] = [
        {"role": "system", "content": "Static instructions."},
        {"role": "system", "content": "Dynamic instructions."},
        *request["messages"],
    ]

    response = client.post("/v1/chat/completions", json=request)

    assert response.status_code == 400
    assert "System message must be at the beginning." in response.json()["error"]["message"]
    assert client.get("/__recorded").json()["unhandled"] == [{"error": "System message must be at the beginning."}]


def test_a_failing_scripted_answer_is_rejected_and_recorded_as_unhandled(client: TestClient) -> None:
    response = client.post("/v1/chat/completions", json=_request("A prompt without the test case to fix", ["ac_ids"]))

    assert response.status_code == 400
    [unhandled] = client.get("/__recorded").json()["unhandled"]
    assert unhandled["operation"] == "test_case_fixing"
    assert unhandled["error"].startswith("TypeError")

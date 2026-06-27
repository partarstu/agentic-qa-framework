# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Hermetic end-to-end smoke checks for the two core QuAIA flows.

All of our own code runs for real (orchestrator + 4 agents + real Gemini); only
the external boundaries are mocked. Each test asserts on what reached a mocked
boundary, read back from its ``/__recorded`` endpoint:

* Requirements review   -> a non-empty comment reached Jira (REST or MCP).
* Test-case generation  -> real test cases (name + steps) reached Zephyr.
* Test-case generation  -> the created test cases were linked to the originating story.
* Test-case classification -> labels reached Zephyr.
* Test-case review      -> a non-empty "Review Comments" value reached Zephyr.
* Test-case review      -> at least one test case reached the "Review Complete" status.
"""

import time
from collections.abc import Callable

import httpx
import pytest

from tests.smoke.conftest import (
    JIRA_MCP_RECORDED_URL,
    JIRA_REST_RECORDED_URL,
    REVIEW_COMPLETE_STATUS,
    ZEPHYR_RECORDED_URL,
)

pytestmark = pytest.mark.smoke

# The webhook returns only after the whole flow completes, so the recordings are
# already in place; this short poll only absorbs any last write lag.
RECORD_POLL_TIMEOUT = 30.0
RECORD_POLL_INTERVAL = 2.0


def _wait_for_recorded(
    http_client: httpx.Client, url: str, predicate: Callable[[dict], bool]
) -> dict:
    """Poll a mock's /__recorded endpoint until the predicate holds or time runs out."""
    deadline = time.monotonic() + RECORD_POLL_TIMEOUT
    data: dict = {}
    while time.monotonic() < deadline:
        response = http_client.get(url)
        if response.status_code == 200:
            data = response.json()
            if predicate(data):
                return data
        time.sleep(RECORD_POLL_INTERVAL)
    return data


def _wait_for_any_recorded(
    http_client: httpx.Client, urls: dict[str, str], predicate: Callable[[dict[str, dict]], bool]
) -> dict[str, dict]:
    """Poll several /__recorded endpoints together until the predicate holds over all their data.

    Polling them in one loop means a result on any source ends the wait immediately,
    instead of spending the whole timeout on a source that will never satisfy it.
    """
    deadline = time.monotonic() + RECORD_POLL_TIMEOUT
    data: dict[str, dict] = {name: {} for name in urls}
    while time.monotonic() < deadline:
        for name, url in urls.items():
            response = http_client.get(url)
            if response.status_code == 200:
                data[name] = response.json()
        if predicate(data):
            return data
        time.sleep(RECORD_POLL_INTERVAL)
    return data


# --- Requirements review flow ----------------------------------------------------------


def test_requirements_review_webhook_accepted(requirements_review_response: httpx.Response) -> None:
    assert requirements_review_response.status_code == 200, (
        f"Requirements-review webhook failed: "
        f"{requirements_review_response.status_code} {requirements_review_response.text}"
    )


def _has_jira_comment(data: dict[str, dict]) -> bool:
    """True once a non-empty comment is recorded on either the REST or the MCP boundary."""
    rest_comments = data.get("rest", {}).get("comments", [])
    mcp_comments = data.get("mcp", {}).get("comments", [])
    return any(c.get("body", "").strip() for c in rest_comments) or any(
        c.get("comment", "").strip() for c in mcp_comments
    )


def test_review_comment_reached_jira(
    requirements_review_response: httpx.Response, http_client: httpx.Client
) -> None:
    """The agent must post a non-empty review comment to Jira, via REST or MCP."""
    data = _wait_for_any_recorded(
        http_client,
        {"rest": JIRA_REST_RECORDED_URL, "mcp": JIRA_MCP_RECORDED_URL},
        _has_jira_comment,
    )
    assert _has_jira_comment(data), (
        f"No non-empty review comment reached Jira. REST={data['rest']}, MCP={data['mcp']}"
    )


# --- Test-case generation / classification / review flow -------------------------------


def test_test_case_flow_webhook_accepted(test_case_flow_response: httpx.Response) -> None:
    assert test_case_flow_response.status_code == 200, (
        f"Test-case flow webhook failed: "
        f"{test_case_flow_response.status_code} {test_case_flow_response.text}"
    )


def test_real_test_cases_created_in_zephyr(
    test_case_flow_response: httpx.Response, http_client: httpx.Client
) -> None:
    """Generation must create real test cases (non-empty name + steps) in Zephyr."""
    data = _wait_for_recorded(
        http_client,
        ZEPHYR_RECORDED_URL,
        lambda d: any(tc.get("name", "").strip() and tc.get("steps") for tc in d.get("test_cases", [])),
    )
    real_cases = [tc for tc in data.get("test_cases", []) if tc.get("name", "").strip() and tc.get("steps")]
    assert real_cases, f"Zephyr received no test cases with both a name and steps. Recorded: {data}"


def test_generated_test_cases_linked_to_story(
    test_case_flow_response: httpx.Response, http_client: httpx.Client
) -> None:
    """Generation must link the created test cases back to the originating story."""
    data = _wait_for_recorded(http_client, ZEPHYR_RECORDED_URL, lambda d: bool(d.get("issue_links")))
    created_keys = {tc.get("key") for tc in data.get("test_cases", [])}
    links = [
        link
        for link in data.get("issue_links", [])
        if link.get("test_case_key") in created_keys and link.get("issue_id")
    ]
    assert links, f"No created test case was linked to the originating story. Recorded: {data}"


def test_classification_added_labels(
    test_case_flow_response: httpx.Response, http_client: httpx.Client
) -> None:
    """Classification must add labels to at least one test case in Zephyr."""
    data = _wait_for_recorded(
        http_client,
        ZEPHYR_RECORDED_URL,
        lambda d: any(tc.get("labels") for tc in d.get("test_cases", [])),
    )
    labelled = [tc for tc in data.get("test_cases", []) if tc.get("labels")]
    assert labelled, f"No test case received labels from classification. Recorded: {data}"


def test_review_comment_added_to_zephyr(
    test_case_flow_response: httpx.Response, http_client: httpx.Client
) -> None:
    """Review must write a non-empty "Review Comments" value to at least one test case."""
    data = _wait_for_recorded(
        http_client,
        ZEPHYR_RECORDED_URL,
        lambda d: any(tc.get("review_comments", "").strip() for tc in d.get("test_cases", [])),
    )
    reviewed = [tc for tc in data.get("test_cases", []) if tc.get("review_comments", "").strip()]
    assert reviewed, f"No test case received a non-empty review comment. Recorded: {data}"


def test_review_set_status_to_review_complete(
    test_case_flow_response: httpx.Response, http_client: httpx.Client
) -> None:
    """Review must move at least one test case to the "Review Complete" status."""
    data = _wait_for_recorded(
        http_client,
        ZEPHYR_RECORDED_URL,
        lambda d: any(tc.get("status", {}).get("name") == REVIEW_COMPLETE_STATUS for tc in d.get("test_cases", [])),
    )
    completed = [tc for tc in data.get("test_cases", []) if tc.get("status", {}).get("name") == REVIEW_COMPLETE_STATUS]
    assert completed, f"No test case was moved to '{REVIEW_COMPLETE_STATUS}'. Recorded: {data}"

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

from unittest.mock import MagicMock, patch

import pytest

from common.models import TestCase, TestExecutionResult, TestStep, TestStepResult
from common.services.zephyr_client import ZephyrClient


@pytest.fixture
def zephyr_client():
    with (
        patch("config.ZEPHYR_BASE_URL", "http://zephyr"),
        patch("config.JIRA_USER", "user"),
        patch("config.ZEPHYR_API_TOKEN", "token"),
    ):
        return ZephyrClient()


@patch("httpx.Client.post")
def test_create_test_cases(mock_post, zephyr_client):
    # Setup for multiple calls:
    # 1. Create Test Case -> returns {"key": "TEST-1"}
    # 2. Link Issue -> returns {}
    # 3. If steps were present, there would be another call.

    mock_post.side_effect = [
        MagicMock(status_code=201, json=lambda: {"key": "TEST-1", "id": 100}),  # Create
        MagicMock(status_code=201, json=lambda: {}),  # Link
    ]

    test_cases = [
        TestCase(
            key=None,
            name="TC1",
            summary="Sum",
            steps=[],
            test_data=[],
            expected_results=[],
            labels=[],
            comment="",
            preconditions="",
            parent_issue_key="STORY-1",
        )
    ]

    keys = zephyr_client.create_test_cases(test_cases, "PROJ", 123)
    assert keys == ["TEST-1"]
    assert mock_post.call_count == 2


@patch("httpx.Client.get")
@patch("httpx.Client.post")
def test_create_test_execution(mock_post, mock_get, zephyr_client):
    mock_post.return_value.status_code = 201
    mock_post.return_value.json.return_value = {"id": "EXEC-1"}

    # Mock _get_test_steps response
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"values": []}  # No steps in existing TC

    results = [
        TestExecutionResult(
            stepResults=[],
            testCaseKey="TEST-1",
            testCaseName="TC1",
            testExecutionStatus="passed",
            generalErrorMessage="",
            start_timestamp="2023-01-01T10:00:00",
            end_timestamp="2023-01-01T10:01:00",
        )
    ]

    zephyr_client.create_test_execution(results, "PROJ", "CYCLE-1")

    assert mock_get.called
    assert mock_post.called


@patch("httpx.Client.get")
@patch("httpx.Client.post")
def test_create_test_execution_ignores_invalid_timestamps(mock_post, mock_get, zephyr_client):
    mock_post.return_value.status_code = 201
    mock_post.return_value.json.return_value = {"id": "EXEC-1"}

    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"values": []}

    results = [
        TestExecutionResult(
            stepResults=[
                TestStepResult(
                    stepDescription="Step 1",
                    success=True,
                    actualResults="OK",
                    errorMessage="",
                    testData=[],
                    expectedResults="",
                    executionStartTimestamp="not-a-timestamp",
                    executionEndTimestamp="not-a-timestamp",
                )
            ],
            testCaseKey="TEST-1",
            testCaseName="TC1",
            testExecutionStatus="passed",
            generalErrorMessage="",
            start_timestamp="2023-01-01T10:00:00,unexpected",
            end_timestamp="not-a-timestamp",
        )
    ]

    zephyr_client.create_test_execution(results, "PROJ", "CYCLE-1")

    payload = mock_post.call_args.kwargs["json"]
    assert payload["actualStartDate"] == "2023-01-01T10:00:00Z"
    assert "actualEndDate" not in payload
    assert "actualStartDate" not in payload["testScriptResults"][0]
    assert "actualEndDate" not in payload["testScriptResults"][0]


@patch("httpx.Client.get")
@patch("httpx.Client.post")
def test_create_test_execution_reports_step_timestamps(mock_post, mock_get, zephyr_client):
    mock_post.return_value.status_code = 201
    mock_post.return_value.json.return_value = {"id": "EXEC-1"}

    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"values": []}

    results = [
        TestExecutionResult(
            stepResults=[
                TestStepResult(
                    stepDescription="Step 1",
                    success=True,
                    actualResults="OK",
                    errorMessage="",
                    testData=[],
                    expectedResults="",
                    executionStartTimestamp="2023-01-01T10:00:05",
                    executionEndTimestamp="2023-01-01T10:00:09",
                )
            ],
            testCaseKey="TEST-1",
            testCaseName="TC1",
            testExecutionStatus="passed",
            generalErrorMessage="",
            start_timestamp="2023-01-01T10:00:00",
            end_timestamp="2023-01-01T10:01:00",
        )
    ]

    zephyr_client.create_test_execution(results, "PROJ", "CYCLE-1")

    step_entry = mock_post.call_args.kwargs["json"]["testScriptResults"][0]
    assert step_entry["actualStartDate"] == "2023-01-01T10:00:05Z"
    assert step_entry["actualEndDate"] == "2023-01-01T10:00:09Z"


@patch("httpx.Client.post")
def test_create_test_plan(mock_post, zephyr_client):
    mock_post.return_value.status_code = 201
    mock_post.return_value.json.return_value = {"key": "CYCLE-1"}

    key = zephyr_client.create_test_plan("PROJ", "Cycle Name")
    assert key == "CYCLE-1"


@patch("httpx.Client.post")
def test_link_issue_to_test_case(mock_post, zephyr_client):
    mock_post.return_value.status_code = 201

    zephyr_client.link_issue_to_test_case("TC-123", 10001, "Relates")

    assert mock_post.called
    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"issueId": 10001, "type": "Relates"}


def test_fetch_test_cases_by_project_resolves_status_names_from_the_catalog(zephyr_client):
    """A listed test case references its status by id only; the name comes from the status catalog."""
    pages = {
        0: {"values": [{"key": "PROJ-T1", "status": {"id": 2, "self": "http://zephyr/statuses/2"}}], "isLast": False},
        100: {"values": [{"key": "PROJ-T2", "status": {"id": 1, "self": "http://zephyr/statuses/1"}}], "isLast": True},
    }

    def _respond(request_fn, url, **kwargs):
        if "/statuses" in url:
            return MagicMock(json=lambda: {"values": [{"id": 1, "name": "Draft"}, {"id": 2, "name": "Approved"}]})
        page = pages[kwargs["params"]["startAt"]]
        return MagicMock(json=lambda: page)

    with (
        patch.object(ZephyrClient, "_request", side_effect=_respond),
        patch.object(
            ZephyrClient,
            "_parse_tc_json",
            side_effect=lambda client, key, tc: TestCase(
                key=tc["key"],
                name="N",
                summary="S",
                steps=[],
                labels=[],
                comment="",
                preconditions="",
                parent_issue_key=None,
            ),
        ),
    ):
        listed = zephyr_client.fetch_test_cases_by_project("PROJ")

    assert [(item.test_case.key, item.status) for item in listed] == [("PROJ-T1", "Approved"), ("PROJ-T2", "Draft")]

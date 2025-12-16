
import pytest
from unittest.mock import MagicMock, patch
from common.services.xray_client import XrayClient
from common.models import TestCase, TestStep, TestExecutionResult, TestStepResult

@pytest.fixture
def xray_client():
    with patch("config.XRAY_BASE_URL", "http://xray"), \
         patch("config.XRAY_CLIENT_ID", "id"), \
         patch("config.XRAY_CLIENT_SECRET", "secret"), \
         patch("config.JIRA_BASE_URL", "http://jira"), \
         patch("config.JIRA_USER", "user"), \
         patch("config.JIRA_TOKEN", "token"), \
         patch("common.services.xray_client.XrayClient._get_token", return_value="mock_token"):
        return XrayClient()

@patch("httpx.Client.request")
@patch("httpx.Client.post")
def test_create_test_cases(mock_post, mock_request, xray_client):
    # create_test_cases calls:
    # 1. _execute_jira_request("POST", "issue/bulk") -> uses mock_request
    # 2. _add_steps_to_test_case -> _execute_graphql_query -> uses mock_post
    # 3. _execute_jira_request("POST", "issueLink") -> uses mock_request
    
    # Mock Jira Bulk Create
    mock_request.side_effect = [
        MagicMock(status_code=201, json=lambda: {"issues": [{"key": "TEST-1", "id": "100"}]}), # Bulk Create
        MagicMock(status_code=201, json=lambda: {}), # Link
    ]
    
    # Mock GraphQL for adding steps
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"data": {"updateTest": {"warnings": []}}}
    
    test_cases = [TestCase(key=None, name="TC1", summary="Sum", steps=[TestStep(action="A", expected_results="E", test_data=[])], 
                           test_data=[], expected_results=[], labels=[], comment="", preconditions="", parent_issue_key="STORY-1")]
    
    keys = xray_client.create_test_cases(test_cases, "PROJ", "STORY-1")
    assert keys == ["TEST-1"]
    assert mock_request.call_count == 2
    assert mock_post.called

@patch("httpx.Client.request")
def test_create_test_execution(mock_request, xray_client):
    # create_test_execution calls _execute_xray_request -> uses mock_request
    mock_request.return_value.status_code = 200
    mock_request.return_value.json.return_value = {"id": "EXEC-1"}
    
    results = [TestExecutionResult(
        stepResults=[], testCaseKey="TEST-1", testCaseName="TC1", 
        testExecutionStatus="passed", generalErrorMessage="", logs="", 
        start_timestamp="2023-01-01T10:00:00", end_timestamp="2023-01-01T10:01:00"
    )]
    
    xray_client.create_test_execution(results, "PROJ", "PLAN-1")
    assert mock_request.called
    # Check if correct URL was hit
    args, kwargs = mock_request.call_args
    assert "import/execution" in args[1]

@patch("httpx.Client.post")
def test_create_test_plan(mock_post, xray_client):
    # create_test_plan calls _execute_graphql_query -> uses mock_post
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "data": {
            "createTestPlan": {
                "testPlan": {
                    "jira": {"key": "PLAN-1"}
                }
            }
        }
    }
    
    key = xray_client.create_test_plan("PROJ", "Plan Name")
    assert key == "PLAN-1"

@patch("httpx.Client.post")
def test_fetch_test_cases_by_jira_issue(mock_post, xray_client):
    # calls _fetch_test_cases_by_jql -> _execute_graphql_query -> mock_post
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "data": {
            "getTests": {
                "results": [
                    {
                        "issueId": "TEST-1",
                        "jira": {"summary": "TC1", "labels": [], "parent": {"key": "STORY-1"}},
                        "steps": []
                    }
                ]
            }
        }
    }
    
    tcs = xray_client.fetch_test_cases_by_jira_issue("STORY-1")
    assert len(tcs) == 1
    assert tcs[0].key == "TEST-1"

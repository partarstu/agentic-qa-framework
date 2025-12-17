
import pytest
from unittest.mock import MagicMock, patch
from common.services.zephyr_client import ZephyrClient
from common.models import TestCase, TestStep, TestExecutionResult, TestStepResult

@pytest.fixture
def zephyr_client():
    with patch("config.ZEPHYR_BASE_URL", "http://zephyr"), \
         patch("config.JIRA_USER", "user"), \
         patch("config.ZEPHYR_API_TOKEN", "token"):
        return ZephyrClient()

@patch("httpx.Client.post")
def test_create_test_cases(mock_post, zephyr_client):
    # Setup for multiple calls:
    # 1. Create Test Case -> returns {"key": "TEST-1"}
    # 2. Link Issue -> returns {}
    # 3. If steps were present, there would be another call.
    
    mock_post.side_effect = [
        MagicMock(status_code=201, json=lambda: {"key": "TEST-1", "id": 100}), # Create
        MagicMock(status_code=201, json=lambda: {}), # Link
    ]
    
    test_cases = [TestCase(key=None, name="TC1", summary="Sum", steps=[], test_data=[], expected_results=[], labels=[], comment="", preconditions="", parent_issue_key="STORY-1")]
    
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
    mock_get.return_value.json.return_value = {"values": []} # No steps in existing TC
    
    results = [TestExecutionResult(
        stepResults=[], testCaseKey="TEST-1", testCaseName="TC1", 
        testExecutionStatus="passed", generalErrorMessage="", logs="", 
        start_timestamp="2023-01-01T10:00:00", end_timestamp="2023-01-01T10:01:00"
    )]
    
    zephyr_client.create_test_execution(results, "PROJ", "CYCLE-1")
    
    assert mock_get.called
    assert mock_post.called

@patch("httpx.Client.post")
def test_create_test_plan(mock_post, zephyr_client):
    mock_post.return_value.status_code = 201
    mock_post.return_value.json.return_value = {"key": "CYCLE-1"}
    
    key = zephyr_client.create_test_plan("PROJ", "Cycle Name")
    assert key == "CYCLE-1"


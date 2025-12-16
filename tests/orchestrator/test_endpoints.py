
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient
from orchestrator.main import orchestrator_app, _validate_api_key
from a2a.types import Task, TaskStatus, TaskState, Artifact, TextPart
import config

client = TestClient(orchestrator_app)

# Override auth dependency
def mock_validate_api_key():
    pass

orchestrator_app.dependency_overrides[_validate_api_key] = mock_validate_api_key

@pytest.fixture
def mock_task_completed():
    task = MagicMock(spec=Task)
    task.status = TaskStatus(state=TaskState.completed)
    task.artifacts = [
        Artifact(
            artifactId="art-1",
            parts=[TextPart(text='{"message": "success"}')]
        )
    ]
    return task

@pytest.mark.asyncio
async def test_review_jira_requirements_endpoint(mock_task_completed):
    with patch("orchestrator.main._choose_agent_id", new_callable=AsyncMock) as mock_choose, \
         patch("orchestrator.main._send_task_to_agent", new_callable=AsyncMock) as mock_send:
        
        mock_choose.return_value = "agent-1"
        mock_send.return_value = mock_task_completed
        
        response = client.post("/new-requirements-available", json={"issue_key": "TEST-1"})
        
        assert response.status_code == 200
        assert "completed" in response.json()["message"]
        mock_choose.assert_called_once()
        mock_send.assert_called_once()

@pytest.mark.asyncio
async def test_review_jira_requirements_no_issue_key():
    response = client.post("/new-requirements-available", json={})
    assert response.status_code == 400
    assert "no Jira issue key" in response.json()["detail"]

@pytest.mark.asyncio
async def test_trigger_test_case_generation_workflow(mock_task_completed):
    # This endpoint calls multiple agents in sequence.
    # _request_test_cases_generation -> returns GeneratedTestCases
    # _request_test_cases_classification
    # _request_test_cases_review
    
    with patch("orchestrator.main._request_test_cases_generation", new_callable=AsyncMock) as mock_gen, \
         patch("orchestrator.main._request_test_cases_classification", new_callable=AsyncMock) as mock_class, \
         patch("orchestrator.main._request_test_cases_review", new_callable=AsyncMock) as mock_review:
        
        mock_gen_obj = MagicMock()
        mock_gen_obj.test_cases = [MagicMock()]
        mock_gen.return_value = mock_gen_obj
        
        response = client.post("/story-ready-for-test-case-generation", json={"issue_key": "TEST-1"})
        
        assert response.status_code == 200
        mock_gen.assert_called_once()
        mock_class.assert_called_once()
        mock_review.assert_called_once()

@pytest.mark.asyncio
async def test_execute_tests_endpoint():
    # This is complex. It fetches TCs, groups them, executes them, generates report.
    # We'll mock the high level functions.
    
    with patch("orchestrator.main.get_test_management_client") as mock_get_client, \
         patch("orchestrator.main._group_test_cases_by_labels", new_callable=AsyncMock) as mock_group, \
         patch("orchestrator.main._request_all_test_cases_execution", new_callable=AsyncMock) as mock_exec, \
         patch("orchestrator.main._generate_test_report", new_callable=AsyncMock) as mock_report:
         
         mock_tm_client = MagicMock()
         mock_get_client.return_value = mock_tm_client
         mock_tm_client.fetch_ready_for_execution_test_cases_by_labels.return_value = {
             config.OrchestratorConfig.AUTOMATED_TC_LABEL: [MagicMock()]
         }
         
         mock_group.return_value = {"UI": [MagicMock()]}
         mock_exec.return_value = [MagicMock()] # results
         
         response = client.post("/execute-tests", json={"project_key": "PROJ"})
         
         assert response.status_code == 200
         mock_exec.assert_called_once()
         mock_report.assert_called_once()


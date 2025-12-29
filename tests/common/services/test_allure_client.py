

import pytest
from unittest.mock import MagicMock, patch
from common.services.allure_client import AllureClient
from common.models import TestExecutionResult, TestStepResult
from a2a.types import FileWithBytes
import os
import datetime
from allure_commons.model2 import Status

@pytest.fixture
def mock_logger_cls():
    with patch("common.services.allure_client.AllureFileLogger") as mock:
        yield mock

@pytest.fixture
def allure_client(tmp_path, mock_logger_cls):
    # Use a temporary directory for the client initialization
    with patch("config.ALLURE_RESULTS_DIR", "allure-results"), \
         patch("config.ALLURE_REPORT_DIR", "allure-report"):
        return AllureClient(str(tmp_path))

def test_generate_report_with_results(mock_logger_cls, allure_client):
    mock_logger = mock_logger_cls.return_value
    
    # Mock subprocess.run to avoid calling real allure
    with patch("subprocess.run") as mock_run:
        results = [TestExecutionResult(
            stepResults=[TestStepResult(stepDescription="Step 1", success=True, actualResults="OK", errorMessage="", testData=[], expectedResults="")], 
            testCaseKey="TEST-1", 
            testCaseName="TC1", 
            testExecutionStatus="passed", 
            generalErrorMessage="", 
            start_timestamp="2023-01-01T10:00:00Z", 
            end_timestamp="2023-01-01T10:01:00Z",
            artifacts=[FileWithBytes(name="screen", bytes=b"MTIz", mime_type="image/png")]
        )]
        
        allure_client.generate_report(results)
        
        assert mock_logger.report_result.called
        # Verify result content passed to logger
        test_result = mock_logger.report_result.call_args[0][0]
        assert test_result.name == "TC1"
        assert test_result.status == Status.PASSED
        assert len(test_result.steps) == 1
        assert len(test_result.attachments) == 1
        assert test_result.attachments[0].name == "screen"

def test_generate_report_failed(mock_logger_cls, allure_client):
    mock_logger = mock_logger_cls.return_value
    with patch("subprocess.run"):
        import base64
        logs_content = "Error logs"
        encoded_logs = base64.b64encode(logs_content.encode('utf-8')).decode('utf-8')
        
        results = [TestExecutionResult(
            stepResults=[], 
            testCaseKey="TEST-2", 
            testCaseName="TC2", 
            testExecutionStatus="failed", 
            generalErrorMessage="Failure msg", 
            start_timestamp="2023-01-01T10:00:00Z", 
            end_timestamp="2023-01-01T10:01:00Z",
            artifacts=[
                FileWithBytes(name="execution_logs.txt", bytes=encoded_logs, mime_type="text/plain")
            ]
        )]
        
        allure_client.generate_report(results)
        
        assert mock_logger.report_result.called
        test_result = mock_logger.report_result.call_args[0][0]
        assert test_result.name == "TC2"
        assert test_result.status == Status.FAILED
        assert test_result.statusDetails.message == "Failure msg"
        assert test_result.statusDetails.trace == logs_content

def test_generate_html_call(allure_client):
    # Verify subprocess call structure
    with patch("subprocess.run") as mock_run:
         allure_client._generate_html()
         mock_run.assert_called_once()
         args = mock_run.call_args[0][0]
         assert "generate" in args
         assert "--single-file" in args

def test_clean_directories(allure_client):
    # Setup some dummy files
    results_dir = allure_client.results_dir
    report_dir = allure_client.report_dir
    os.makedirs(results_dir, exist_ok=True)
    os.makedirs(report_dir, exist_ok=True)
    
    (results_dir / "dummy.txt").touch()
    (report_dir / "dummy.html").touch()
    
    allure_client._clean_directories()
    
    assert not (results_dir / "dummy.txt").exists()
    assert not (report_dir / "dummy.html").exists()
    assert results_dir.exists()
    assert report_dir.exists()

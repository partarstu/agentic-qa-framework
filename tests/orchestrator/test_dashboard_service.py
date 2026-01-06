
import pytest
from datetime import datetime
from unittest.mock import MagicMock
from orchestrator.dashboard_service import OrchestratorDashboardService
from orchestrator.models import AgentRegistry, TaskHistory, ErrorHistory

@pytest.fixture
def mock_dashboard_service():
    registry = MagicMock(spec=AgentRegistry)
    tasks = MagicMock(spec=TaskHistory)
    errors = MagicMock(spec=ErrorHistory)
    return OrchestratorDashboardService(registry, tasks, errors)

def test_parse_agent_logs_standard(mock_dashboard_service):
    raw_logs = [
        "2026-01-01 12:00:00,000 - agent - INFO - normal message",
        "2026-01-01 12:00:01,000 - agent - ERROR - error message"
    ]
    parsed = mock_dashboard_service._parse_agent_logs(raw_logs, "task-1", "agent-1")
    assert len(parsed) == 2
    assert parsed[0].level == "INFO"
    assert parsed[1].level == "ERROR"

def test_parse_agent_logs_json_with_error_field(mock_dashboard_service):
    # This matches the user's issue: JSON with "error" field should NOT be classified as ERROR level
    # if it doesn't look like a log line
    json_log = '{"error": "some data", "status": "failed"}'
    # Without timestamp, it might trigger fallback
    
    raw_logs = [json_log]
    parsed = mock_dashboard_service._parse_agent_logs(raw_logs, "task-1", "agent-1")
    
    assert len(parsed) == 1
    # Should default to INFO, not ERROR (which was the bug)
    assert parsed[0].level == "INFO"
    assert parsed[0].message == json_log

def test_parse_agent_logs_multiline_json(mock_dashboard_service):
    raw_logs = [
        "2026-01-01 12:00:00 - agent - INFO - Sending request:",
        "{",
        '  "error": "none",',
        '  "data": "value"',
        "}"
    ]
    parsed = mock_dashboard_service._parse_agent_logs(raw_logs, "task-1", "agent-1")
    
    assert len(parsed) == 5
    # First line is standard
    assert parsed[0].level == "INFO"
    
    # Subsequent lines (JSON parts) should NOT be detected as ERROR just because 'error' is in text
    assert parsed[2].level == "INFO"
    assert 'error' in parsed[2].message

def test_parse_agent_logs_real_log_format(mock_dashboard_service):
    # Test with the format that comes from AgentLogCaptureHandler
    # '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    raw_logs = [
        "2026-01-06 16:20:30,123 - my_agent - INFO - {\"error\": \"data\"}"
    ]
    parsed = mock_dashboard_service._parse_agent_logs(raw_logs, "task-1", "agent-1")
    
    assert len(parsed) == 1
    assert parsed[0].level == "INFO"
    assert parsed[0].message == '{"error": "data"}'

def test_parse_agent_logs_fallback_timestamp(mock_dashboard_service):
    # Verify that when timestamp is missing, we get an empty string
    raw_logs = ["Just a message"]
    parsed = mock_dashboard_service._parse_agent_logs(raw_logs, "task-1", "agent-1")
    
    assert len(parsed) == 1
    # Check that timestamp is empty
    assert parsed[0].timestamp == ""

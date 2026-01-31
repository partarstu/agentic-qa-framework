# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for orchestrator parsing logic functions.

Tests cover:
- _get_text_content_from_artifacts: Extracts text content from artifacts as a list of strings.
- _get_model_from_artifacts: Parses artifacts into specific models or AgentExecutionError.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.types import Artifact, FilePart, FileWithBytes, Part, TextPart

from common.models import (
    AgentExecutionError,
    GeneratedTestCases,
    IncidentCreationResult,
    JsonSerializableModel,
)
from orchestrator.main import (
    _get_model_from_artifacts,
    _get_text_content_from_artifacts,
)

# =============================================================================
# Helper Functions and Fixtures
# =============================================================================


def _create_text_artifact(texts: list[str]) -> Artifact:
    """Helper to create an artifact with text parts."""
    parts = [Part(root=TextPart(text=text)) for text in texts]
    return Artifact(artifactId="test-artifact", parts=parts)


def _create_file_artifact(filename: str = "test.txt") -> Artifact:
    """Helper to create an artifact with a file part."""
    file_part = FilePart(file=FileWithBytes(name=filename, mimeType="text/plain", bytes=b"content"))
    return Artifact(artifactId="file-artifact", parts=[Part(root=file_part)])


def _create_mixed_artifact(text: str, filename: str = "test.txt") -> Artifact:
    """Helper to create an artifact with both text and file parts."""
    text_part = Part(root=TextPart(text=text))
    file_part = Part(root=FilePart(file=FileWithBytes(name=filename, mimeType="text/plain", bytes=b"content")))
    return Artifact(artifactId="mixed-artifact", parts=[text_part, file_part])


class SampleModel(JsonSerializableModel):
    """Sample model for testing _get_model_from_artifacts."""

    name: str
    value: int


@pytest.fixture
def mock_error_history():
    """Mock error_history to prevent asyncio event loop issues in sync tests."""
    with patch("orchestrator.main.error_history") as mock:
        mock.add = AsyncMock()
        yield mock


# =============================================================================
# Tests for _get_text_content_from_artifacts
# =============================================================================


class TestGetTextContentFromArtifacts:
    """Tests for _get_text_content_from_artifacts function."""

    def test_single_artifact_single_text_part(self):
        """Test extracting text from a single artifact with one text part."""
        artifacts = [_create_text_artifact(["Hello, World!"])]

        result = _get_text_content_from_artifacts(artifacts, "test task")

        assert result == ["Hello, World!"]

    def test_single_artifact_multiple_text_parts(self):
        """Test extracting text from a single artifact with multiple text parts."""
        artifacts = [_create_text_artifact(["Part 1", "Part 2", "Part 3"])]

        result = _get_text_content_from_artifacts(artifacts, "test task")

        assert result == ["Part 1", "Part 2", "Part 3"]

    def test_multiple_artifacts_each_with_text(self):
        """Test extracting text from multiple artifacts."""
        artifacts = [
            _create_text_artifact(["Artifact 1 Text"]),
            _create_text_artifact(["Artifact 2 Text"]),
        ]

        result = _get_text_content_from_artifacts(artifacts, "test task")

        assert result == ["Artifact 1 Text", "Artifact 2 Text"]

    def test_multiple_artifacts_multiple_parts_each(self):
        """Test extracting text from multiple artifacts with multiple parts each."""
        artifacts = [
            _create_text_artifact(["A1P1", "A1P2"]),
            _create_text_artifact(["A2P1", "A2P2", "A2P3"]),
        ]

        result = _get_text_content_from_artifacts(artifacts, "test task")

        assert result == ["A1P1", "A1P2", "A2P1", "A2P2", "A2P3"]

    @pytest.mark.asyncio
    async def test_empty_artifacts_list_content_expected(self, mock_error_history):
        """Test empty artifacts list when content is expected raises exception."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _get_text_content_from_artifacts([], "test task", any_content_expected=True)

        assert exc_info.value.status_code == 500
        assert "no text results" in exc_info.value.detail.lower()

    def test_empty_artifacts_list_content_not_expected(self):
        """Test empty artifacts list when content is not expected returns empty list."""
        result = _get_text_content_from_artifacts([], "test task", any_content_expected=False)

        assert result == []

    @pytest.mark.asyncio
    async def test_none_artifacts_content_expected(self, mock_error_history):
        """Test None artifacts when content is expected raises exception."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _get_text_content_from_artifacts(None, "test task", any_content_expected=True)

        assert exc_info.value.status_code == 500

    def test_none_artifacts_content_not_expected(self):
        """Test None artifacts when content is not expected returns empty list."""
        result = _get_text_content_from_artifacts(None, "test task", any_content_expected=False)

        assert result == []

    @pytest.mark.asyncio
    async def test_file_parts_only_content_expected(self, mock_error_history):
        """Test artifacts with only file parts when content is expected raises exception."""
        from fastapi import HTTPException

        artifacts = [_create_file_artifact()]

        with pytest.raises(HTTPException) as exc_info:
            _get_text_content_from_artifacts(artifacts, "test task", any_content_expected=True)

        assert exc_info.value.status_code == 500

    def test_file_parts_only_content_not_expected(self):
        """Test artifacts with only file parts when content is not expected returns empty list."""
        artifacts = [_create_file_artifact()]

        result = _get_text_content_from_artifacts(artifacts, "test task", any_content_expected=False)

        assert result == []

    def test_mixed_parts_extracts_only_text(self):
        """Test that mixed artifacts extract only text parts, ignoring file parts."""
        artifacts = [_create_mixed_artifact("Text content")]

        result = _get_text_content_from_artifacts(artifacts, "test task")

        assert result == ["Text content"]

    def test_empty_text_parts_are_excluded(self):
        """Test that empty text parts are excluded from results."""
        artifact = Artifact(
            artifactId="test",
            parts=[
                Part(root=TextPart(text="Valid text")),
                Part(root=TextPart(text="")),
                Part(root=TextPart(text="Another valid")),
            ],
        )

        result = _get_text_content_from_artifacts([artifact], "test task")

        assert result == ["Valid text", "Another valid"]

    def test_whitespace_only_text_is_included(self):
        """Test that whitespace-only text parts are included (they're non-empty)."""
        artifact = Artifact(
            artifactId="test",
            parts=[Part(root=TextPart(text="  "))],
        )

        result = _get_text_content_from_artifacts([artifact], "test task")

        assert result == ["  "]


# =============================================================================
# Tests for _get_model_from_artifacts
# =============================================================================


class TestGetModelFromArtifacts:
    """Tests for _get_model_from_artifacts function."""

    def test_parse_valid_model_successfully(self):
        """Test parsing valid JSON into the expected model type."""
        json_content = '{"name": "test", "value": 42}'
        artifacts = [_create_text_artifact([json_content])]

        result = _get_model_from_artifacts(artifacts, "test task", SampleModel)

        assert isinstance(result, SampleModel)
        assert result.name == "test"
        assert result.value == 42

    def test_parse_agent_execution_error(self):
        """Test that AgentExecutionError JSON is correctly recognized and returned."""
        error_json = '{"error_message": "Something went wrong during execution"}'
        artifacts = [_create_text_artifact([error_json])]

        result = _get_model_from_artifacts(artifacts, "test task", SampleModel)

        assert isinstance(result, AgentExecutionError)
        assert result.error_message == "Something went wrong during execution"

    def test_parse_agent_execution_error_with_complex_message(self):
        """Test AgentExecutionError with complex error message."""
        error_json = '{"error_message": "Failed to connect to service: timeout after 30s, retries: 3"}'
        artifacts = [_create_text_artifact([error_json])]

        result = _get_model_from_artifacts(artifacts, "test task", SampleModel)

        assert isinstance(result, AgentExecutionError)
        assert "timeout after 30s" in result.error_message

    def test_parse_incident_creation_result(self):
        """Test parsing IncidentCreationResult model."""
        json_content = '{"incident_id": 12345, "incident_key": "BUG-123", "duplicates": []}'
        artifacts = [_create_text_artifact([json_content])]

        result = _get_model_from_artifacts(artifacts, "test task", IncidentCreationResult)

        assert isinstance(result, IncidentCreationResult)
        assert result.incident_id == 12345
        assert result.incident_key == "BUG-123"
        assert result.duplicates == []

    def test_parse_generated_test_cases(self):
        """Test parsing GeneratedTestCases model."""
        json_content = """{
            "test_cases": [
                {
                    "key": "TC-001",
                    "labels": ["ui", "smoke"],
                    "name": "Login Test",
                    "summary": "Test user login",
                    "comment": "Check credentials",
                    "preconditions": "User exists",
                    "steps": [],
                    "parent_issue_key": "STORY-1"
                }
            ]
        }"""
        artifacts = [_create_text_artifact([json_content])]

        result = _get_model_from_artifacts(artifacts, "test task", GeneratedTestCases)

        assert isinstance(result, GeneratedTestCases)
        assert len(result.test_cases) == 1
        assert result.test_cases[0].key == "TC-001"

    @pytest.mark.asyncio
    async def test_multiple_text_parts_raises_exception(self, mock_error_history):
        """Test that multiple text parts in artifacts raises exception."""
        from fastapi import HTTPException

        artifacts = [_create_text_artifact(["part1", "part2"])]

        with pytest.raises(HTTPException) as exc_info:
            _get_model_from_artifacts(artifacts, "test task", SampleModel)

        assert exc_info.value.status_code == 500
        assert "exactly one text artifact" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_no_text_parts_raises_exception(self, mock_error_history):
        """Test that no text parts raises exception."""
        from fastapi import HTTPException

        artifacts = [_create_file_artifact()]

        with pytest.raises(HTTPException) as exc_info:
            _get_model_from_artifacts(artifacts, "test task", SampleModel)

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_invalid_json_raises_exception(self, mock_error_history):
        """Test that invalid JSON raises exception."""
        from fastapi import HTTPException

        artifacts = [_create_text_artifact(["not valid json"])]

        with pytest.raises(HTTPException) as exc_info:
            _get_model_from_artifacts(artifacts, "test task", SampleModel)

        assert exc_info.value.status_code == 500
        assert "failed to parse" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_wrong_schema_raises_exception(self, mock_error_history):
        """Test that JSON with wrong schema for model raises exception."""
        from fastapi import HTTPException

        # Valid JSON but wrong schema for SampleModel
        json_content = '{"wrong_field": "value"}'
        artifacts = [_create_text_artifact([json_content])]

        with pytest.raises(HTTPException) as exc_info:
            _get_model_from_artifacts(artifacts, "test task", SampleModel)

        assert exc_info.value.status_code == 500
        assert "failed to parse" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_empty_artifacts_raises_exception(self, mock_error_history):
        """Test that empty artifacts list raises exception."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            _get_model_from_artifacts([], "test task", SampleModel)

    @pytest.mark.asyncio
    async def test_none_artifacts_raises_exception(self, mock_error_history):
        """Test that None artifacts raises exception."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            _get_model_from_artifacts(None, "test task", SampleModel)

    @pytest.mark.asyncio
    async def test_error_message_includes_truncated_content(self, mock_error_history):
        """Test that parse error message includes truncated content for debugging."""
        from fastapi import HTTPException

        # Create very long invalid JSON
        long_content = "x" * 1000
        artifacts = [_create_text_artifact([long_content])]

        with pytest.raises(HTTPException) as exc_info:
            _get_model_from_artifacts(artifacts, "test task", SampleModel)

        # Error should contain truncated content (first 500 chars + "...")
        assert "..." in exc_info.value.detail

    def test_prioritizes_agent_execution_error_over_model(self):
        """Test that AgentExecutionError is detected before attempting model parsing.

        This ensures that if an agent returns an error in the expected JSON format,
        it's properly detected even if the error JSON might also be valid for the
        target model (unlikely but possible with permissive schemas).
        """
        error_json = '{"error_message": "Agent failed"}'
        artifacts = [_create_text_artifact([error_json])]

        # Even when expecting a different model, AgentExecutionError takes precedence
        result = _get_model_from_artifacts(artifacts, "test task", SampleModel)

        assert isinstance(result, AgentExecutionError)

    def test_handles_json_with_extra_fields(self):
        """Test that model parsing handles JSON with extra fields gracefully."""
        # JSON with extra fields not in model
        json_content = '{"name": "test", "value": 42, "extra_field": "ignored"}'
        artifacts = [_create_text_artifact([json_content])]

        result = _get_model_from_artifacts(artifacts, "test task", SampleModel)

        assert isinstance(result, SampleModel)
        assert result.name == "test"
        assert result.value == 42

    def test_handles_nullable_fields_in_error(self):
        """Test AgentExecutionError with various error message formats."""
        # Error with special characters
        error_json = '{"error_message": "Error: Connection failed\\nDetails: timeout"}'
        artifacts = [_create_text_artifact([error_json])]

        result = _get_model_from_artifacts(artifacts, "test task", SampleModel)

        assert isinstance(result, AgentExecutionError)
        assert "Connection failed" in result.error_message


# =============================================================================
# Integration Tests for Higher-Level Functions
# =============================================================================


class TestRequestIncidentCreationErrorHandling:
    """Tests for AgentExecutionError handling in _request_incident_creation."""

    @pytest.mark.asyncio
    async def test_returns_none_on_agent_execution_error(self, mock_error_history):
        """Test that _request_incident_creation returns None when agent returns error."""
        from common.models import IncidentCreationInput, TestCase

        # Create a mock test case
        test_case = TestCase(
            key="TC-001",
            labels=["ui"],
            name="Test Case",
            summary="Test summary",
            comment="",
            preconditions="",
            steps=[],
            parent_issue_key="STORY-1",
        )

        incident_input = IncidentCreationInput(
            test_case=test_case,
            test_execution_result="Test failed",
            test_step_results=[],
            system_description="Test system",
            issue_priority_field_id="priority_field_id",
        )

        # Create artifact with AgentExecutionError
        error_json = '{"error_message": "Failed to create incident: API rate limit exceeded"}'
        error_artifact = _create_text_artifact([error_json])

        with patch("orchestrator.main._send_task_to_agent_with_message", new_callable=AsyncMock) as mock_send, \
             patch("orchestrator.main._get_artifacts_from_task") as mock_get_artifacts:

            mock_task = MagicMock()
            mock_task.artifacts = [error_artifact]
            mock_send.return_value = mock_task
            mock_get_artifacts.return_value = [error_artifact]

            from orchestrator.main import _request_incident_creation

            result = await _request_incident_creation(incident_input, [])

            assert result is None

    @pytest.mark.asyncio
    async def test_returns_result_on_success(self, mock_error_history):
        """Test that _request_incident_creation returns result on success."""
        from common.models import IncidentCreationInput, TestCase

        test_case = TestCase(
            key="TC-001",
            labels=["ui"],
            name="Test Case",
            summary="Test summary",
            comment="",
            preconditions="",
            steps=[],
            parent_issue_key="STORY-1",
        )

        incident_input = IncidentCreationInput(
            test_case=test_case,
            test_execution_result="Test failed",
            test_step_results=[],
            system_description="Test system",
            issue_priority_field_id="priority_field_id",
        )

        # Create artifact with successful result
        success_json = '{"incident_id": 12345, "incident_key": "BUG-123", "duplicates": []}'
        success_artifact = _create_text_artifact([success_json])

        with patch("orchestrator.main._send_task_to_agent_with_message", new_callable=AsyncMock) as mock_send, \
             patch("orchestrator.main._get_artifacts_from_task") as mock_get_artifacts:

            mock_task = MagicMock()
            mock_task.artifacts = [success_artifact]
            mock_send.return_value = mock_task
            mock_get_artifacts.return_value = [success_artifact]

            from orchestrator.main import _request_incident_creation

            result = await _request_incident_creation(incident_input, [])

            assert result is not None
            assert result.incident_key == "BUG-123"
            assert result.incident_id == 12345


class TestRequestTestCasesGenerationErrorHandling:
    """Tests for AgentExecutionError handling in _request_test_cases_generation."""

    @pytest.mark.asyncio
    async def test_raises_exception_on_agent_execution_error(self, mock_error_history):
        """Test that _request_test_cases_generation raises exception when agent returns error."""
        from fastapi import HTTPException

        # Create artifact with AgentExecutionError
        error_json = '{"error_message": "Failed to generate test cases: User story not found"}'
        error_artifact = _create_text_artifact([error_json])

        with patch("orchestrator.main._send_task_to_agent", new_callable=AsyncMock) as mock_send, \
             patch("orchestrator.main._get_artifacts_from_task") as mock_get_artifacts:

            mock_task = MagicMock()
            mock_task.artifacts = [error_artifact]
            mock_send.return_value = mock_task
            mock_get_artifacts.return_value = [error_artifact]

            from orchestrator.main import _request_test_cases_generation

            with pytest.raises(HTTPException) as exc_info:
                await _request_test_cases_generation("STORY-123")

            assert "test case generation failed" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_returns_test_cases_on_success(self, mock_error_history):
        """Test that _request_test_cases_generation returns test cases on success."""
        # Create artifact with successful result
        success_json = """{
            "test_cases": [
                {
                    "key": "TC-001",
                    "labels": [],
                    "name": "Generated Test",
                    "summary": "Test summary",
                    "comment": "",
                    "preconditions": null,
                    "steps": [],
                    "parent_issue_key": "STORY-123"
                }
            ]
        }"""
        success_artifact = _create_text_artifact([success_json])

        with patch("orchestrator.main._send_task_to_agent", new_callable=AsyncMock) as mock_send, \
             patch("orchestrator.main._get_artifacts_from_task") as mock_get_artifacts:

            mock_task = MagicMock()
            mock_task.artifacts = [success_artifact]
            mock_send.return_value = mock_task
            mock_get_artifacts.return_value = [success_artifact]

            from orchestrator.main import _request_test_cases_generation

            result = await _request_test_cases_generation("STORY-123")

            assert result is not None
            assert len(result.test_cases) == 1
            assert result.test_cases[0].key == "TC-001"


class TestExecuteSingleTestMultipleTextParts:
    """Tests for _execute_single_test handling of multiple text parts."""

    @pytest.mark.asyncio
    async def test_joins_multiple_text_parts(self, mock_error_history):
        """Test that _execute_single_test joins multiple text parts correctly."""
        from common.models import TestCase

        test_case = TestCase(
            key="TC-001",
            labels=["ui"],
            name="Test Case",
            summary="Test summary",
            comment="",
            preconditions="",
            steps=[],
            parent_issue_key="STORY-1",
        )

        # Create artifact with multiple text parts
        multi_part_artifact = _create_text_artifact([
            '{"stepResults": [], "testCaseKey": "TC-001", ',
            '"testCaseName": "Test Case", "testExecutionStatus": "passed", ',
            '"generalErrorMessage": "", "start_timestamp": "2025-01-01", "end_timestamp": "2025-01-01"}'
        ])

        # We need to mock the entire test execution flow
        with patch("orchestrator.main._send_task_to_agent", new_callable=AsyncMock) as mock_send, \
             patch("orchestrator.main._get_artifacts_from_task") as mock_get_artifacts, \
             patch("orchestrator.main.agent_registry") as mock_registry, \
             patch("orchestrator.main._get_results_extractor_agent") as mock_extractor:

            mock_task = MagicMock()
            mock_task.artifacts = [multi_part_artifact]
            mock_send.return_value = mock_task
            mock_get_artifacts.return_value = [multi_part_artifact]
            mock_registry.get_name = AsyncMock(return_value="Test Agent")

            # Mock the results extractor to return a proper TestExecutionResult
            from common.models import TestExecutionResult
            mock_result = TestExecutionResult(
                stepResults=[],
                testCaseKey="TC-001",
                testCaseName="Test Case",
                testExecutionStatus="passed",
                generalErrorMessage="",
                start_timestamp="2025-01-01",
                end_timestamp="2025-01-01",
            )
            mock_extractor_instance = AsyncMock()
            mock_extractor_instance.run.return_value.output = mock_result
            mock_extractor.return_value = mock_extractor_instance

            from orchestrator.main import _execute_single_test

            await _execute_single_test("agent-1", test_case, "ui")

            # Verify that the extractor was called with joined text parts
            mock_extractor_instance.run.assert_called_once()
            call_args = mock_extractor_instance.run.call_args[0][0]
            # The joined content should contain all parts
            assert "stepResults" in call_args
            assert "testExecutionStatus" in call_args
            assert "passed" in call_args

    @pytest.mark.asyncio
    async def test_handles_single_text_part(self, mock_error_history):
        """Test that _execute_single_test handles single text part correctly."""
        from common.models import TestCase

        test_case = TestCase(
            key="TC-002",
            labels=["api"],
            name="API Test",
            summary="Test API",
            comment="",
            preconditions="",
            steps=[],
            parent_issue_key="STORY-2",
        )

        # Create artifact with single text part
        single_part_result = '{"stepResults": [], "testCaseKey": "TC-002", "testCaseName": "API Test", "testExecutionStatus": "failed", "generalErrorMessage": "API error", "start_timestamp": "2025-01-01", "end_timestamp": "2025-01-01"}'
        single_part_artifact = _create_text_artifact([single_part_result])

        with patch("orchestrator.main._send_task_to_agent", new_callable=AsyncMock) as mock_send, \
             patch("orchestrator.main._get_artifacts_from_task") as mock_get_artifacts, \
             patch("orchestrator.main.agent_registry") as mock_registry, \
             patch("orchestrator.main._get_results_extractor_agent") as mock_extractor:

            mock_task = MagicMock()
            mock_task.artifacts = [single_part_artifact]
            mock_send.return_value = mock_task
            mock_get_artifacts.return_value = [single_part_artifact]
            mock_registry.get_name = AsyncMock(return_value="Test Agent")

            from common.models import TestExecutionResult
            mock_result = TestExecutionResult(
                stepResults=[],
                testCaseKey="TC-002",
                testCaseName="API Test",
                testExecutionStatus="failed",
                generalErrorMessage="API error",
                start_timestamp="2025-01-01",
                end_timestamp="2025-01-01",
            )
            mock_extractor_instance = AsyncMock()
            mock_extractor_instance.run.return_value.output = mock_result
            mock_extractor.return_value = mock_extractor_instance

            from orchestrator.main import _execute_single_test

            result = await _execute_single_test("agent-1", test_case, "api")

            assert result is not None
            assert result.testExecutionStatus == "failed"

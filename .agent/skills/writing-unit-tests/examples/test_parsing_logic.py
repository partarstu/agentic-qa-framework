# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Example: Unit tests for artifact parsing functions.

These tests verify _get_text_content_from_artifacts and _get_model_from_artifacts.
"""

from unittest.mock import AsyncMock, patch

import pytest
from a2a.types import Artifact, FilePart, FileWithBytes, Part, TextPart

from common.models import AgentExecutionError, JsonSerializableModel
from orchestrator.main import (
    _get_model_from_artifacts,
    _get_text_content_from_artifacts,
)


def _create_text_artifact(texts: list[str]) -> Artifact:
    """Helper to create an artifact with text parts."""
    parts = [Part(root=TextPart(text=text)) for text in texts]
    return Artifact(artifactId="test-artifact", parts=parts)


def _create_file_artifact(filename: str = "test.txt") -> Artifact:
    """Helper to create an artifact with a file part."""
    file_part = FilePart(file=FileWithBytes(name=filename, mimeType="text/plain", bytes=b"content"))
    return Artifact(artifactId="file-artifact", parts=[Part(root=file_part)])


class SampleModel(JsonSerializableModel):
    """Sample model for testing."""
    name: str
    value: int


@pytest.fixture
def mock_error_history():
    """Mock error_history to prevent asyncio event loop issues."""
    with patch("orchestrator.main.error_history") as mock:
        mock.add = AsyncMock()
        yield mock


class TestGetTextContentFromArtifacts:
    """Tests for _get_text_content_from_artifacts function."""

    def test_single_artifact_single_text_part(self):
        """Test extracting text from a single artifact with one text part."""
        artifacts = [_create_text_artifact(["Hello, World!"])]
        result = _get_text_content_from_artifacts(artifacts, "test task")
        assert result == ["Hello, World!"]

    def test_multiple_artifacts_multiple_parts(self):
        """Test extracting text from multiple artifacts."""
        artifacts = [
            _create_text_artifact(["Part 1", "Part 2"]),
            _create_text_artifact(["Part 3"]),
        ]
        result = _get_text_content_from_artifacts(artifacts, "test task")
        assert result == ["Part 1", "Part 2", "Part 3"]

    @pytest.mark.asyncio
    async def test_empty_artifacts_raises_exception(self, mock_error_history):
        """Test empty artifacts raises exception when content expected."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _get_text_content_from_artifacts([], "test task", any_content_expected=True)
        
        assert exc_info.value.status_code == 500

    def test_empty_artifacts_returns_empty_when_not_expected(self):
        """Test empty artifacts returns empty list when content not expected."""
        result = _get_text_content_from_artifacts([], "test task", any_content_expected=False)
        assert result == []


class TestGetModelFromArtifacts:
    """Tests for _get_model_from_artifacts function."""

    def test_parse_valid_model(self):
        """Test parsing valid JSON into model."""
        json_content = '{"name": "test", "value": 42}'
        artifacts = [_create_text_artifact([json_content])]
        
        result = _get_model_from_artifacts(artifacts, "test task", SampleModel)
        
        assert isinstance(result, SampleModel)
        assert result.name == "test"
        assert result.value == 42

    def test_parse_agent_execution_error(self):
        """Test AgentExecutionError is correctly recognized."""
        error_json = '{"error_message": "Something went wrong"}'
        artifacts = [_create_text_artifact([error_json])]
        
        result = _get_model_from_artifacts(artifacts, "test task", SampleModel)
        
        assert isinstance(result, AgentExecutionError)
        assert result.error_message == "Something went wrong"

    @pytest.mark.asyncio
    async def test_invalid_json_raises_exception(self, mock_error_history):
        """Test invalid JSON raises exception."""
        from fastapi import HTTPException

        artifacts = [_create_text_artifact(["not valid json"])]
        
        with pytest.raises(HTTPException) as exc_info:
            _get_model_from_artifacts(artifacts, "test task", SampleModel)
        
        assert "failed to parse" in exc_info.value.detail.lower()

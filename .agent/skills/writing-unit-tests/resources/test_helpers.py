# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Test helper utilities for creating mock objects.

These helpers can be used across different test files.
"""

from unittest.mock import AsyncMock, MagicMock

from a2a.types import AgentCapabilities, AgentCard, Artifact, FilePart, FileWithBytes, Part, TextPart


def create_text_artifact(texts: list[str]) -> Artifact:
    """Helper to create an artifact with text parts."""
    parts = [Part(root=TextPart(text=text)) for text in texts]
    return Artifact(artifactId="test-artifact", parts=parts)


def create_file_artifact(filename: str = "test.txt", content: bytes = b"content") -> Artifact:
    """Helper to create an artifact with a file part."""
    file_part = FilePart(
        file=FileWithBytes(name=filename, mimeType="text/plain", bytes=content)
    )
    return Artifact(artifactId="file-artifact", parts=[Part(root=file_part)])


def create_mixed_artifact(text: str, filename: str = "test.txt") -> Artifact:
    """Helper to create an artifact with both text and file parts."""
    text_part = Part(root=TextPart(text=text))
    file_part = Part(root=FilePart(
        file=FileWithBytes(name=filename, mimeType="text/plain", bytes=b"content")
    ))
    return Artifact(artifactId="mixed-artifact", parts=[text_part, file_part])


def create_mock_agent_card(
    name: str = "Test Agent",
    url: str = "http://localhost:8001",
    description: str = "Test description"
) -> AgentCard:
    """Create a mock AgentCard for testing."""
    return AgentCard(
        name=name,
        description=description,
        url=url,
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=[],
        defaultInputModes=['text'],
        defaultOutputModes=['text']
    )


def create_mock_error_history():
    """Create a mock error_history to prevent asyncio event loop issues."""
    mock = MagicMock()
    mock.add = AsyncMock()
    return mock

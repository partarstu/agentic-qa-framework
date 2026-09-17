# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Shared deterministic rendering helpers for the test-case vector index."""

import hashlib
import uuid
from datetime import UTC, datetime

from common.models import ListedTestCase, VectorizableBaseModel


class IndexedTestCase(VectorizableBaseModel):
    """The payload and embedding content for one test-case index point."""

    source: str = "test_case"
    project_key: str
    test_case_key: str
    name: str
    status: str
    labels: list[str]
    parent_issue_key: str | None
    text: str
    content_hash: str
    indexed_at: str

    def get_vector_id(self) -> str:
        """Return a stable UUID scoped to the configured test-management identity."""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"quaia:test-case:{self.test_case_key}"))

    def get_embedding_content(self) -> str:
        """Return the compact human-readable test-case representation."""
        return self.text


def render_test_case(project_key: str, listed: ListedTestCase) -> IndexedTestCase:
    """Render a listed test case into a deterministic index record."""
    test_case = listed.test_case
    steps = "\n".join(
        f"- Action: {step.action}; Data: {', '.join(step.test_data)}; Expected: {step.expected_results}"
        for step in test_case.steps
    )
    text = "\n".join(
        part for part in (f"Name: {test_case.name}", f"Objective: {test_case.summary}", f"Preconditions: {test_case.preconditions or ''}", steps) if part
    )
    return IndexedTestCase(
        project_key=project_key, test_case_key=test_case.key or "", name=test_case.name, status=listed.status,
        labels=test_case.labels, parent_issue_key=test_case.parent_issue_key, text=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(), indexed_at=datetime.now(UTC).isoformat(),
    )

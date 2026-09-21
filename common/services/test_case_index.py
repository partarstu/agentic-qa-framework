# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Deterministic rendering of a test case into its vector index record."""

import hashlib
import uuid
from datetime import UTC, datetime

from common.models import TestCase, VectorizableBaseModel


class IndexedTestCase(VectorizableBaseModel):
    source: str = "test_case"
    project_key: str
    test_case_key: str
    text: str
    content_hash: str
    indexed_at: str

    def get_vector_id(self) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"quaia:test-case:{self.test_case_key}"))

    def get_embedding_content(self) -> str:
        return self.text


def render_test_case(project_key: str, test_case: TestCase) -> IndexedTestCase:
    steps = "\n".join(
        f"- Action: {step.action}; Data: {', '.join(step.test_data)}; Expected: {step.expected_results}"
        for step in test_case.steps
    )
    text = "\n".join(
        part
        for part in (
            f"Name: {test_case.name}",
            f"Objective: {test_case.summary}",
            f"Preconditions: {test_case.preconditions or ''}",
            steps,
        )
        if part
    )
    return IndexedTestCase(
        project_key=project_key,
        test_case_key=test_case.key or "",
        text=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        indexed_at=datetime.now(UTC).isoformat(),
    )

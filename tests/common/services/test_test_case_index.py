# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import uuid

from common.models import TestCase, TestStep
from common.services.test_case_index import render_test_case


def _test_case(key: str) -> TestCase:
    return TestCase(
        key=key,
        name="Login",
        summary="Log in with valid credentials",
        comment="",
        preconditions="A registered user",
        steps=[TestStep(action="Submit the form", expected_results="The dashboard opens", test_data=["user: a"])],
        labels=[],
        parent_issue_key="PROJ-1",
    )


def test_point_id_is_derived_from_the_key_only():
    record = render_test_case("PROJ", _test_case("PROJ-T1"))

    assert record.get_vector_id() == str(uuid.uuid5(uuid.NAMESPACE_URL, "quaia:test-case:PROJ-T1"))


def test_point_id_is_stable_across_renders():
    assert (
        render_test_case("PROJ", _test_case("PROJ-T1")).get_vector_id()
        == render_test_case("PROJ", _test_case("PROJ-T1")).get_vector_id()
    )


def test_payload_holds_only_the_index_fields():
    record = render_test_case("PROJ", _test_case("PROJ-T1"))

    assert set(record.model_dump()) == {"source", "project_key", "test_case_key", "text", "content_hash", "indexed_at"}
    assert record.source == "test_case"
    assert record.project_key == "PROJ"
    assert record.test_case_key == "PROJ-T1"


def test_rendered_text_covers_name_objective_preconditions_and_steps():
    text = render_test_case("PROJ", _test_case("PROJ-T1")).text

    assert "Name: Login" in text
    assert "Objective: Log in with valid credentials" in text
    assert "Preconditions: A registered user" in text
    assert "Action: Submit the form; Data: user: a; Expected: The dashboard opens" in text

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import uuid

from common.models import DesignedTestCase, TestCase, TestStep
from common.services.test_case_index import (
    render_designed_test_case_block,
    render_designed_test_case_text,
    render_test_case,
    render_test_case_text,
)


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


def test_compact_text_is_the_indexed_text_without_any_key_label_or_comment():
    test_case = _test_case("PROJ-T1").model_copy(update={"labels": ["ui"], "comment": "generated"})

    text = render_test_case_text(test_case)

    assert text == render_test_case("PROJ", test_case).text
    assert "PROJ-T1" not in text
    assert "ui" not in text
    assert "generated" not in text


def test_a_designed_test_case_is_the_compact_text_followed_by_its_acceptance_criteria():
    test_case = DesignedTestCase(**_test_case("PROJ-T1").model_dump(), ac_ids=["AC-1", "AC-3"])

    text = render_designed_test_case_text(test_case)

    assert text == f"{render_test_case_text(test_case)}\n\nAcceptance criteria: AC-1, AC-3"


def test_the_sections_of_a_test_case_are_separated_by_a_blank_line():
    text = render_test_case_text(_test_case("PROJ-T1"))

    assert text.split("\n\n") == [
        "Name: Login",
        "Objective: Log in with valid credentials",
        "Preconditions: A registered user",
        "- Action: Submit the form; Data: user: a; Expected: The dashboard opens",
    ]


def test_a_designed_test_case_block_is_its_fenced_text_under_the_heading():
    test_case = DesignedTestCase(**_test_case("PROJ-T1").model_dump(), ac_ids=["AC-1"])

    block = render_designed_test_case_block("ID DRAFT-1", test_case)

    assert block == f"ID DRAFT-1:\n```{render_designed_test_case_text(test_case)}```"

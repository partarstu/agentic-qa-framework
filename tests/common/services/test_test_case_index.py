# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for the shared test-case index rendering (WS17)."""

import uuid

from common.models import ListedTestCase, TestCase, TestStep
from common.services.test_case_index import render_test_case


def _listed(key: str) -> ListedTestCase:
    test_case = TestCase(
        key=key,
        name="Login",
        summary="Log in with valid credentials",
        comment="",
        preconditions="A registered user",
        steps=[TestStep(action="Submit the form", expected_results="The dashboard opens", test_data=["user: a"])],
        labels=[],
        parent_issue_key="PROJ-1",
    )
    return ListedTestCase(test_case=test_case, status="Draft")


def test_point_id_is_derived_from_the_test_management_system_and_the_key(monkeypatch):
    monkeypatch.setattr("config.TEST_MANAGEMENT_SYSTEM", "zephyr")

    record = render_test_case("PROJ", _listed("PROJ-T1"))

    assert record.test_management_system == "zephyr"
    assert record.get_vector_id() == str(uuid.uuid5(uuid.NAMESPACE_URL, "quaia:test-case:zephyr:PROJ-T1"))


def test_same_key_in_another_test_management_system_gets_another_point_id(monkeypatch):
    monkeypatch.setattr("config.TEST_MANAGEMENT_SYSTEM", "zephyr")
    zephyr_id = render_test_case("PROJ", _listed("PROJ-T1")).get_vector_id()
    monkeypatch.setattr("config.TEST_MANAGEMENT_SYSTEM", "xray")
    xray_id = render_test_case("PROJ", _listed("PROJ-T1")).get_vector_id()

    assert zephyr_id != xray_id


def test_point_id_is_stable_across_renders():
    assert (
        render_test_case("PROJ", _listed("PROJ-T1")).get_vector_id()
        == render_test_case("PROJ", _listed("PROJ-T1")).get_vector_id()
    )


def test_rendered_text_covers_name_objective_preconditions_and_steps():
    text = render_test_case("PROJ", _listed("PROJ-T1")).text

    assert "Name: Login" in text
    assert "Objective: Log in with valid credentials" in text
    assert "Preconditions: A registered user" in text
    assert "Action: Submit the form; Data: user: a; Expected: The dashboard opens" in text

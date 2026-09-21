# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parents[2] / ".agents" / "skills" / "implementing-changes" / "scripts" / "coverage.py"
COVERAGE = runpy.run_path(str(SCRIPT_PATH))
COVERAGE_REPORT = """<?xml version="1.0" ?>
<coverage lines-valid="3" lines-covered="2">
    <packages>
        <package name="common">
            <classes>
                <class name="Calc.py" filename="common/Calc.py">
                    <lines>
                        <line number="1" hits="1"/>
                        <line number="2" hits="1"/>
                        <line number="3" hits="0"/>
                    </lines>
                </class>
            </classes>
        </package>
    </packages>
</coverage>
"""
SOURCE_PATH = "common/Calc.py"
TEST_PATH = "tests/test_calc.py"
TEMPLATE_PATH = ".agents/skills/adding-orchestrator-workflow/resources/endpoint_template.py"


def _diff(*paths: str) -> str:
    return "".join(f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-a\n+b\n" for path in paths)


def _run_coverage(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *args: str) -> str:
    monkeypatch.setattr(sys, "argv", ["coverage.py", *args])
    COVERAGE["main"]()
    return capsys.readouterr().out


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "coverage.xml").write_text(COVERAGE_REPORT, encoding="utf-8")
    return repository


@pytest.fixture
def diff_file(tmp_path: Path) -> Path:
    run_directory = tmp_path / "run"
    run_directory.mkdir()
    return run_directory / "task.diff"


@pytest.fixture
def fake_diff_cover(monkeypatch: pytest.MonkeyPatch, diff_file: Path):
    def fake(src_stats: dict) -> None:
        def run(*args, **kwargs) -> None:
            (diff_file.parent / "diff-cover.json").write_text(json.dumps({"src_stats": src_stats}), encoding="utf-8")

        monkeypatch.setattr(subprocess, "run", run)

    return fake


def test_prints_the_total_coverage_rounded_down(
    repository: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output = _run_coverage(monkeypatch, capsys, str(repository))

    assert output == "TOTAL COVERAGE: 66.66% (2 of 3 lines)\n"


def test_fails_without_a_coverage_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["coverage.py", str(tmp_path)])

    with pytest.raises(SystemExit, match=r"No coverage\.xml"):
        COVERAGE["main"]()


def test_counts_only_the_changed_source_lines(
    repository: Path,
    diff_file: Path,
    fake_diff_cover,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    diff_file.write_text(_diff(SOURCE_PATH, TEST_PATH, TEMPLATE_PATH, "README.md"), encoding="utf-8")
    # diff-cover reports the paths in lower case on Windows.
    fake_diff_cover(
        {
            SOURCE_PATH.lower(): {"covered_lines": [1, 2], "violation_lines": [3]},
            TEST_PATH: {"covered_lines": [1, 2, 3, 4, 5], "violation_lines": []},
        }
    )

    output = _run_coverage(monkeypatch, capsys, str(repository), str(diff_file))

    assert output.splitlines()[1:] == [
        "CHANGED-LINE COVERAGE: 66.66% (2 of 3 lines)",
        "UNCOVERED CHANGED LINES:",
        f"- {SOURCE_PATH}: 3",
    ]


def test_reports_when_no_changed_source_line_has_coverage_data(
    repository: Path,
    diff_file: Path,
    fake_diff_cover,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    diff_file.write_text(_diff(TEST_PATH, "README.md"), encoding="utf-8")
    fake_diff_cover({TEST_PATH: {"covered_lines": [1], "violation_lines": []}})

    output = _run_coverage(monkeypatch, capsys, str(repository), str(diff_file))

    assert output.splitlines()[1:] == ["CHANGED-LINE COVERAGE: no changed lines with coverage data"]


def test_fails_for_a_changed_source_file_without_coverage_data(
    repository: Path, diff_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    diff_file.write_text(_diff(SOURCE_PATH, "common/unimported.py"), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["coverage.py", str(repository), str(diff_file)])

    with pytest.raises(SystemExit, match=r"no test imports them: common/unimported\.py$"):
        COVERAGE["main"]()

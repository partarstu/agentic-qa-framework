# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parents[2] / ".agents" / "skills" / "implementing-changes" / "scripts" / "task_diff.py"
TASK_DIFF = runpy.run_path(str(SCRIPT_PATH))
GIT_TIMEOUT_SECONDS = 60


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *args], check=True, timeout=GIT_TIMEOUT_SECONDS, capture_output=True, text=True
    ).stdout


def _run_task_diff(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *args: str) -> str:
    monkeypatch.setattr(sys, "argv", ["task_diff.py", *args])
    TASK_DIFF["main"]()
    return capsys.readouterr().out


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    (repository / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    _git(repository, "add", "--all")
    _git(
        repository,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--quiet",
        "--message=initial",
    )
    monkeypatch.chdir(repository)
    return repository


def test_diff_contains_only_changes_made_after_the_snapshot(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_directory = str(tmp_path / "run")
    with (repository / "calc.py").open("a", encoding="utf-8") as calc:
        calc.write("\n\ndef sub(a, b):\n    return a - b\n")
    (repository / "notes.txt").write_text("existing work\n", encoding="utf-8")
    base_tree = _run_task_diff(monkeypatch, capsys, run_directory).strip()

    with (repository / "calc.py").open("a", encoding="utf-8") as calc:
        calc.write("\n\ndef mul(a, b):\n    return a * b\n")
    (repository / "new_module.py").write_text("VALUE = 1\n", encoding="utf-8")
    changed_paths = _run_task_diff(monkeypatch, capsys, run_directory, base_tree)

    diff = (Path(run_directory) / "task.diff").read_text(encoding="utf-8")
    assert changed_paths.splitlines() == ["M\tcalc.py", "A\tnew_module.py"]
    assert "+def mul(a, b):" in diff
    assert "+VALUE = 1" in diff
    assert "+def sub(a, b):" not in diff
    assert "notes.txt" not in diff


def test_snapshot_and_diff_leave_the_git_index_untouched(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_directory = str(tmp_path / "run")
    (repository / "new_module.py").write_text("VALUE = 1\n", encoding="utf-8")

    base_tree = _run_task_diff(monkeypatch, capsys, run_directory).strip()
    _run_task_diff(monkeypatch, capsys, run_directory, base_tree)

    assert _git(repository, "diff", "--cached", "--name-only") == ""
    assert _git(repository, "status", "--porcelain") == "?? new_module.py\n"


@pytest.mark.parametrize("base_tree", ["HEAD", "abc123", "--output=diff.txt"])
def test_rejects_a_base_tree_that_is_not_a_tree_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base_tree: str
) -> None:
    monkeypatch.setattr(sys, "argv", ["task_diff.py", str(tmp_path / "run"), base_tree])

    with pytest.raises(SystemExit):
        TASK_DIFF["main"]()

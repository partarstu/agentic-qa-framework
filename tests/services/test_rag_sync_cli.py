# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Unit tests for starting the sync runtime's entry points from the repository (WS11 local development)."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("entry_point", ["services.rag_sync.cli", "services.rag_sync.local_service"])
def test_entry_point_started_from_the_repository_root_resolves_the_runtime_packages(entry_point: str) -> None:
    # A fresh interpreter, because the test session itself already has services/ on sys.path.
    script = f"import {entry_point}; import rag_sync.jira_sync; import rag_sync.confluence_sync"

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.fixture
def cli():
    """The runner module imported in-process, as the repository layout resolves it."""
    import services.rag_sync.cli as cli_module

    return cli_module


def test_jira_run_exits_zero_on_completion(cli, monkeypatch) -> None:
    from common.models import RagUpdateResult

    monkeypatch.setattr(sys, "argv", ["cli", "jira", "--project-key", "PROJ", "--lock-token", "tok"])
    with patch("rag_sync.jira_sync.JiraRagSyncRunner") as runner_cls:
        runner_cls.return_value.sync_project = AsyncMock(
            return_value=RagUpdateResult(status="completed", processed_count=1)
        )

        assert cli.main() == 0

    runner_cls.return_value.sync_project.assert_awaited_once_with("PROJ", lock_token="tok")


def test_confluence_run_with_item_failures_exits_two(cli, monkeypatch) -> None:
    from common.models import RagUpdateResult

    monkeypatch.setattr(sys, "argv", ["cli", "confluence", "--space-key", "DEV"])
    with patch("rag_sync.confluence_sync.ConfluenceRagSyncRunner") as runner_cls:
        runner_cls.return_value.sync_space = AsyncMock(
            return_value=RagUpdateResult(status="completed_with_errors", processed_count=1)
        )

        assert cli.main() == 2


@pytest.mark.parametrize(
    ("argv", "runner_path", "method"),
    [
        (["cli", "jira", "--project-key", "PROJ"], "rag_sync.jira_sync.JiraRagSyncRunner", "sync_project"),
        (
            ["cli", "test_cases", "--project-key", "PROJ"],
            "rag_sync.test_case_sync.TestCaseRagSyncRunner",
            "sync_project",
        ),
    ],
    ids=["jira", "test_cases"],
)
def test_every_source_exits_two_on_a_non_clean_run(cli, monkeypatch, argv, runner_path, method) -> None:
    """A job platform must see a non-clean sync whichever source produced it."""
    from common.models import RagUpdateResult

    monkeypatch.setattr(sys, "argv", argv)
    with patch(runner_path) as runner_cls:
        setattr(
            runner_cls.return_value,
            method,
            AsyncMock(return_value=RagUpdateResult(status="completed_with_errors", processed_count=1)),
        )

        assert cli.main() == 2


def test_lost_lock_exits_three(cli, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["cli", "jira", "--project-key", "PROJ"])
    with patch("rag_sync.jira_sync.JiraRagSyncRunner") as runner_cls:
        runner_cls.return_value.sync_project = AsyncMock(side_effect=PermissionError("taken over"))

        assert cli.main() == 3


@pytest.fixture
def report_outcome():
    with patch("rag_sync.outcome_reporting.report_terminal_outcome", new_callable=AsyncMock) as report:
        yield report


def test_sharepoint_run_passes_its_scope_and_reports_the_outcome(cli, monkeypatch, report_outcome) -> None:
    from common.models import RagUpdateResult

    argv = ["cli", "sharepoint", "--drive-id", "d-1", "--folder-path", "Docs", "--attachment-name-pattern", "^spec"]
    monkeypatch.setattr(sys, "argv", argv)
    result = RagUpdateResult(status="completed", processed_count=2)
    with patch("rag_sync.sharepoint_sync.SharePointRagSyncRunner") as runner_cls:
        runner_cls.return_value.sync_drive = AsyncMock(return_value=result)

        assert cli.main() == 0

    runner_cls.return_value.sync_drive.assert_awaited_once_with(
        drive_id="d-1", folder_path="Docs", file_name_pattern="^spec", lock_token=None
    )
    report_outcome.assert_awaited_once_with("sharepoint", "d-1", result=result)


@pytest.mark.parametrize("source", ["jira", "confluence", "sharepoint", "test_cases"])
def test_every_triggered_source_is_a_cli_subcommand_and_a_local_route(cli, monkeypatch, source) -> None:
    """The orchestrator passes its source name as the job's subcommand and as the local /sync/<source> path."""
    from services.rag_sync.local_service import app

    monkeypatch.setattr(sys, "argv", ["cli", source, "--help"])
    with pytest.raises(SystemExit) as exited:
        cli.main()

    assert exited.value.code == 0
    assert f"/sync/{source}" in {route.path for route in app.routes}


def test_test_case_run_reports_a_failure_and_propagates_it(cli, monkeypatch, report_outcome) -> None:
    monkeypatch.setattr(sys, "argv", ["cli", "test_cases", "--project-key", "PROJ"])
    error = RuntimeError("listing failed")
    with patch("rag_sync.test_case_sync.TestCaseRagSyncRunner") as runner_cls:
        runner_cls.return_value.sync_project = AsyncMock(side_effect=error)

        assert cli.main() != 0

    report_outcome.assert_awaited_once_with("test_cases", "PROJ", error=error)

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
            return_value=RagUpdateResult(status="completed-with-errors", processed_count=1)
        )

        assert cli.main() == 2


def test_lost_lock_exits_three(cli, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["cli", "jira", "--project-key", "PROJ"])
    with patch("rag_sync.jira_sync.JiraRagSyncRunner") as runner_cls:
        runner_cls.return_value.sync_project = AsyncMock(side_effect=PermissionError("taken over"))

        assert cli.main() == 3

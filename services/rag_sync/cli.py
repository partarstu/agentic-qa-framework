# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Command-line runner: runs one sync for one scope to completion.

The Cloud Run Job and local one-off runs use this entry point. The exit code reflects
the outcome, so schedulers and job platforms see failures without parsing logs.

Usage:
    python -m services.rag_sync.cli jira --project-key PROJ [--lock-token TOKEN]
    python -m services.rag_sync.cli confluence --space-key DEV [--page-id 123]
        [--attachment-name-pattern PATTERN] [--skip-page-body] [--lock-token TOKEN]
"""

import argparse
import asyncio
import os
import sys

# Make the runtime importable when the runner is started directly. The image copies rag_sync/ next to
# common/, while the repository nests it under services/, so both the package's parent directory
# (for "rag_sync.*") and the one above it (the repository root, for "common.*") go on the path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _exit_code(result) -> int:
    """The one exit-code mapping of a run's outcome, shared by every source.

    0 for a clean run, 2 for a run that finished with item failures, so a job platform
    sees a non-clean sync whichever source produced it.
    """
    # Deferred like every import in this module: the sys.path setup above has to run first.
    from common.models import SyncStatus

    return 0 if result.status == SyncStatus.COMPLETED else 2


async def _run(args: argparse.Namespace) -> int:
    from rag_sync.outcome_reporting import report_terminal_outcome

    if args.source == "jira":
        from rag_sync.jira_sync import JiraRagSyncRunner

        try:
            result = await JiraRagSyncRunner().sync_project(args.project_key, lock_token=args.lock_token)
        except Exception as exc:
            await report_terminal_outcome("jira", args.project_key, error=exc)
            raise
        await report_terminal_outcome("jira", args.project_key, result=result)
        print(f"Jira sync completed: {result.model_dump()}")
        return _exit_code(result)

    if args.source == "sharepoint":
        from rag_sync.sharepoint_sync import SharePointRagSyncRunner

        try:
            result = await SharePointRagSyncRunner().sync_drive(
                drive_id=args.drive_id,
                folder_path=args.folder_path,
                file_name_pattern=args.attachment_name_pattern,
                lock_token=args.lock_token,
            )
        except Exception as exc:
            await report_terminal_outcome("sharepoint", args.drive_id, error=exc)
            raise
        await report_terminal_outcome("sharepoint", args.drive_id, result=result)
        print(f"SharePoint sync completed: {result.model_dump()}")
        return _exit_code(result)

    if args.source == "test_cases":
        from rag_sync.test_case_sync import TestCaseRagSyncRunner

        try:
            result = await TestCaseRagSyncRunner().sync_project(args.project_key, lock_token=args.lock_token)
        except Exception as exc:
            await report_terminal_outcome("test_cases", args.project_key, error=exc)
            raise
        await report_terminal_outcome("test_cases", args.project_key, result=result)
        print(f"Test-case sync completed: {result.model_dump()}")
        return _exit_code(result)

    from rag_sync.confluence_sync import ConfluenceRagSyncRunner

    try:
        result = await ConfluenceRagSyncRunner().sync_space(
            space_key=args.space_key,
            page_id=args.page_id,
            attachment_name_pattern=args.attachment_name_pattern,
            skip_page_body=args.skip_page_body,
            lock_token=args.lock_token,
        )
    except Exception as exc:
        await report_terminal_outcome("confluence", args.space_key, error=exc)
        raise
    await report_terminal_outcome("confluence", args.space_key, result=result)
    print(f"Confluence sync completed: {result.model_dump()}")
    return _exit_code(result)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one RAG sync for one scope to completion.")
    subparsers = parser.add_subparsers(dest="source", required=True)

    jira_parser = subparsers.add_parser("jira", help="Sync a Jira project's issues into the RAG vector DB.")
    jira_parser.add_argument("--project-key", required=True, help="The Jira project key to synchronize.")
    jira_parser.add_argument("--lock-token", help="Holder token issued by the orchestrator, if any.")

    sharepoint_parser = subparsers.add_parser(
        "sharepoint", help="Sync a SharePoint drive (or one folder of it) into the documents collection."
    )
    sharepoint_parser.add_argument("--drive-id", required=True, help="The drive ID to synchronize.")
    sharepoint_parser.add_argument("--folder-path", help="Restrict the sync to one folder's descendants.")
    sharepoint_parser.add_argument("--attachment-name-pattern", help="Regex filtering file names.")
    sharepoint_parser.add_argument("--lock-token", help="Holder token issued by the orchestrator, if any.")

    test_cases_parser = subparsers.add_parser(
        "test_cases", help="Full-resync the test cases of a project into the RAG vector DB."
    )
    test_cases_parser.add_argument("--project-key", required=True, help="The Jira project key to synchronize.")
    test_cases_parser.add_argument("--lock-token", help="Holder token issued by the orchestrator, if any.")

    confluence_parser = subparsers.add_parser(
        "confluence", help="Sync a Confluence space into the documents collection."
    )
    confluence_parser.add_argument("--space-key", required=True, help="The Confluence space key (may start with '~').")
    confluence_parser.add_argument("--page-id", help="Restrict the sync to one page of the space.")
    confluence_parser.add_argument("--attachment-name-pattern", help="Regex filtering attachment file names.")
    confluence_parser.add_argument("--skip-page-body", action="store_true", help="Ingest attachments only.")
    confluence_parser.add_argument("--lock-token", help="Holder token issued by the orchestrator, if any.")

    from common.services.sync_lock_store import SyncLockHeldError

    args = parser.parse_args()
    try:
        return asyncio.run(_run(args))
    except PermissionError as e:
        print(f"Lock lost: {e}", file=sys.stderr)
        return 3
    except SyncLockHeldError as e:
        print(f"Sync not started: {e}", file=sys.stderr)
        return 1
    except Exception:
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

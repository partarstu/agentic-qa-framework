# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Command-line runner: runs one sync for one scope to completion (WS8).

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

# Make the repository root importable when the runner is started directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


async def _run(args: argparse.Namespace) -> int:
    if args.source == "jira":
        from rag_sync.jira_sync import JiraRagSyncRunner

        result = await JiraRagSyncRunner().sync_project(args.project_key, lock_token=args.lock_token)
        print(f"Jira sync completed: {result.model_dump()}")
        return 0

    # The Confluence sync ships in the next phase; the endpoint validation exists already.
    print("The Confluence sync is not implemented yet (ships with the document RAG ingestion).")
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one RAG sync for one scope to completion.")
    subparsers = parser.add_subparsers(dest="source", required=True)

    jira_parser = subparsers.add_parser("jira", help="Sync a Jira project's issues into the RAG vector DB.")
    jira_parser.add_argument("--project-key", required=True, help="The Jira project key to synchronize.")
    jira_parser.add_argument("--lock-token", help="Holder token issued by the orchestrator, if any.")

    confluence_parser = subparsers.add_parser("confluence", help="Sync a Confluence space into the documents collection.")
    confluence_parser.add_argument("--space-key", required=True, help="The Confluence space key (may start with '~').")
    confluence_parser.add_argument("--page-id", help="Restrict the sync to one page of the space.")
    confluence_parser.add_argument("--attachment-name-pattern", help="Regex filtering attachment file names.")
    confluence_parser.add_argument("--skip-page-body", action="store_true", help="Ingest attachments only.")
    confluence_parser.add_argument("--lock-token", help="Holder token issued by the orchestrator, if any.")

    args = parser.parse_args()
    try:
        return asyncio.run(_run(args))
    except PermissionError as e:
        print(f"Lock lost: {e}", file=sys.stderr)
        return 3
    except RuntimeError as e:
        print(f"Sync failed: {e}", file=sys.stderr)
        return 1
    except Exception:
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

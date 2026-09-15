# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""RAG sync runtime: one deployable image separate from the orchestrator (WS8).

Contains the Jira sync (moved from ``common/services/rag_sync_service.py``, same
algorithm apart from the cursor fix), the lock and sync-state store wiring, and two
entry points:

* the command-line runner (``services/rag_sync/cli.py``) runs one sync for one scope
  to completion and exits with an outcome code - the Cloud Run Job and local one-off
  runs use it;
* the local sync service (``services/rag_sync/local_service.py``) exposes the same
  scopes over HTTP for development and debugging, guarded by the internal API key.
"""

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""RAG sync runtime: one deployable image separate from the orchestrator, holding the source syncs and the lock and
sync-state store wiring. Its two entry points are the command-line runner ``cli.py``, which runs one scope to completion
and exits with an outcome code, and ``local_service.py``, which exposes the same scopes over HTTP behind the internal
API key.
"""

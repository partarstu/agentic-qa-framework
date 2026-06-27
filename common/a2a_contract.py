# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""
Contract constants for A2A artifact names produced by this project's agents.

External agents are not required to use these names; the orchestrator identifies
their artifacts by MIME type (text/plain for logs) and TaskStatus.message for
activity — both standard A2A mechanisms.
"""


class ArtifactName:
    """Artifact names emitted by internal agents via TaskArtifactUpdateEvent."""

    LOGS = "logs"
    EXECUTION_RESULT = "agent_execution_result"
    USAGE = "agent_usage"

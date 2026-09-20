# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Contract constants for the A2A artifact names this project's agents produce. External agents need not use them: the
orchestrator identifies their artifacts by MIME type and TaskStatus.message, both standard A2A mechanisms.
"""


class ArtifactName:
    """Artifact names emitted by internal agents via TaskArtifactUpdateEvent."""

    LOGS = "logs"
    EXECUTION_RESULT = "agent_execution_result"
    USAGE = "agent_usage"

# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""
Output model template for a new agent.

Paste into common/models.py, which already imports `Field` and defines `BaseAgentResult`.
Replace <AgentOutput> and <Agent Name>.
"""


class <AgentOutput>(BaseAgentResult):
    """Result of the <Agent Name> agent."""

    field_name: str = Field(description="<Description the LLM uses to fill this field>")

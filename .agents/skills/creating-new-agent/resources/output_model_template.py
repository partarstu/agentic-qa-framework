# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""
Output model template for a new agent.

Add this to common/models.py.
Replace <AgentOutput> and <Agent Name> with appropriate names.
"""

from pydantic import Field

from common.models import BaseAgentResult


class <AgentOutput>(BaseAgentResult):
    """Result from <Agent Name> agent."""
    
    field_name: str = Field(description="Description of this field")
    # Add other fields as needed

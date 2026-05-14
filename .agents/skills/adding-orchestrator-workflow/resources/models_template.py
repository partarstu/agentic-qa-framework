# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Request and Response model templates for orchestrator workflows.

Add these to common/models.py.
Replace <WorkflowName> with your workflow's name.
"""

from pydantic import Field

from common.models import BaseAgentResult, JsonSerializableModel


class <WorkflowName>Request(JsonSerializableModel):
    """Request to trigger <workflow description>."""
    
    field_name: str = Field(description="Description of this field")
    # Add other required fields


class <WorkflowName>Result(BaseAgentResult):
    """Result from <workflow description>."""
    
    result_field: str = Field(description="Description of this field")
    # Add other fields as needed

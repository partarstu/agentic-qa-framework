# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""
Request and result model templates for an orchestrator workflow.

Paste into common/models.py, which already imports `Field` and defines `JsonSerializableModel` and `BaseAgentResult`.
Replace <WorkflowName> and the fields.
"""


class <WorkflowName>Request(JsonSerializableModel):
    """Request that triggers <workflow description>."""

    field_name: str = Field(description="<Description of this field>")


class <WorkflowName>Result(BaseAgentResult):
    """Result the agent returns for <workflow description>."""

    result_field: str = Field(description="<Description the LLM uses to fill this field>")

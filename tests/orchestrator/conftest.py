# SPDX-FileCopyrightText: 2025-2026 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Shared helpers for the orchestrator tests."""

from unittest.mock import MagicMock


def agent_card(name: str = "Agent 1", version: str = "2.5", url: str | None = "http://agent-host:8001") -> MagicMock:
    """An agent card stub carrying the identity fields the orchestrator reads.

    Passing ``url=None`` produces a card without any supported interface.
    """
    card = MagicMock()
    card.name = name
    card.version = version
    card.supported_interfaces = [MagicMock(url=url)] if url else []
    return card

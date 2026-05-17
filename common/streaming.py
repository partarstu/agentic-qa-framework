# SPDX-FileCopyrightText: 2025 Taras Paruta (partarstu@gmail.com)
#
# SPDX-License-Identifier: Apache-2.0

"""
Streaming primitives for A2A activity reporting and SSE event payloads.

StreamEmitter and its ContextVar binding are owned by DefaultAgentExecutor per task.
AgentBase.report_activity resolves the emitter from the same context.
"""

import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel

from common import utils

logger = utils.get_logger("streaming")


# ---------------------------------------------------------------------------
# StreamEmitter
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class StreamEmitter:
    """Carries the streaming callbacks bound to a single task execution."""

    on_activity: Callable[[str], None]
    on_log_batch: Callable[[list[str]], None]


# ---------------------------------------------------------------------------
# ContextVars
# ---------------------------------------------------------------------------

current_emitter: ContextVar[StreamEmitter | None] = ContextVar("current_emitter", default=None)
current_log_handler: ContextVar[object | None] = ContextVar("current_log_handler", default=None)


def set_current_emitter(emitter: StreamEmitter) -> Token:
    """Bind emitter to the current context; returns a reset token."""
    return current_emitter.set(emitter)


def reset_current_emitter(token: Token) -> None:
    """Reset the emitter binding using the token returned by set_current_emitter."""
    current_emitter.reset(token)


def set_current_log_handler(handler: object) -> Token:
    """Bind log handler to the current context; returns a reset token."""
    return current_log_handler.set(handler)


def reset_current_log_handler(token: Token) -> None:
    """Reset the log handler binding using the token returned by set_current_log_handler."""
    current_log_handler.reset(token)


# ---------------------------------------------------------------------------
# report_activity tool
# ---------------------------------------------------------------------------


async def report_activity(description: str) -> None:
    """Report your current activity to the dashboard.

    Call this with one short sentence (≤ 120 chars) describing what you are
    about to do, whenever you start a new reasoning phase OR before invoking
    any other tool. You may and should call it in parallel with other tool
    calls in the same response. Examples: "Fetching Jira issue PROJ-123",
    "Generating test steps for AC-2".
    """
    emitter = current_emitter.get()
    if emitter is None:
        return
    try:
        emitter.on_activity(description)
    except Exception:
        logger.exception("Failed to publish activity; continuing.")


# ---------------------------------------------------------------------------
# Budget helper
# ---------------------------------------------------------------------------


def compute_activity_budget(base_limit: int) -> int:
    """Return the tool-calls limit that accounts for report_activity calls."""
    return base_limit * 2


# ---------------------------------------------------------------------------
# SSE payload event models
# ---------------------------------------------------------------------------


class AgentActivityEvent(BaseModel):
    version: int = 1
    type: str = "agent_activity"
    task_id: str
    agent_id: str
    text: str


class LogBatchEvent(BaseModel):
    version: int = 1
    type: str = "log_batch"
    task_id: str
    lines: list[str]


class TaskDoneEvent(BaseModel):
    version: int = 1
    type: str = "task_done"
    task_id: str
    agent_id: str
    status: str
    error_message: str | None = None


class GapEvent(BaseModel):
    version: int = 1
    type: str = "gap"
    reason: str
    since: int
    until: int


class AgentSnapshot(BaseModel):
    id: str
    name: str
    status: str
    current_task_id: str | None = None


class RunningTaskSnapshot(BaseModel):
    task_id: str
    agent_id: str
    description: str
    current_activity: str | None = None


class SnapshotEvent(BaseModel):
    version: int = 1
    agents: list[AgentSnapshot] = []
    running_tasks: list[RunningTaskSnapshot] = []


class AuthErrorEvent(BaseModel):
    version: int = 1
    type: str = "auth-error"

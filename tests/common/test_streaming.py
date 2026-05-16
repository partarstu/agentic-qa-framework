import asyncio
from unittest.mock import MagicMock

import pytest

from common.streaming import (
    StreamEmitter,
    compute_activity_budget,
    current_emitter,
    report_activity,
    reset_current_emitter,
    set_current_emitter,
)


def _make_emitter(on_activity=None) -> StreamEmitter:
    return StreamEmitter(
        on_activity=on_activity or MagicMock(),
        on_log_batch=MagicMock(),
        on_step_result=MagicMock(),
    )


# ---------------------------------------------------------------------------
# compute_activity_budget
# ---------------------------------------------------------------------------


def test_compute_activity_budget_doubles_base():
    assert compute_activity_budget(5) == 10
    assert compute_activity_budget(1) == 2
    assert compute_activity_budget(100) == 200


# ---------------------------------------------------------------------------
# report_activity — no emitter set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_activity_no_emitter_is_noop():
    """Must not raise when no emitter is bound."""
    assert current_emitter.get() is None
    await report_activity("doing something")  # must not raise


@pytest.mark.asyncio
async def test_report_activity_no_emitter_returns_none():
    result = await report_activity("doing something")
    assert result is None


# ---------------------------------------------------------------------------
# report_activity — emitter set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_activity_calls_on_activity():
    callback = MagicMock()
    emitter = _make_emitter(on_activity=callback)
    token = set_current_emitter(emitter)
    try:
        await report_activity("fetching data")
        callback.assert_called_once_with("fetching data")
    finally:
        reset_current_emitter(token)


@pytest.mark.asyncio
async def test_report_activity_returns_none_with_emitter():
    emitter = _make_emitter()
    token = set_current_emitter(emitter)
    try:
        result = await report_activity("fetching data")
        assert result is None
    finally:
        reset_current_emitter(token)


# ---------------------------------------------------------------------------
# report_activity — emitter callback raises → swallowed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_activity_swallows_callback_error():
    """A raising callback must not propagate; report_activity returns None."""
    def bad_callback(text: str) -> None:
        raise RuntimeError("publish failed")

    emitter = _make_emitter(on_activity=bad_callback)
    token = set_current_emitter(emitter)
    try:
        result = await report_activity("something")
        assert result is None
    finally:
        reset_current_emitter(token)


# ---------------------------------------------------------------------------
# ContextVar isolation — each asyncio Task has its own context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_var_isolated_between_tasks():
    callback_a = MagicMock()
    callback_b = MagicMock()
    emitter_a = _make_emitter(on_activity=callback_a)
    emitter_b = _make_emitter(on_activity=callback_b)

    async def task_a():
        token = set_current_emitter(emitter_a)
        await report_activity("task A")
        reset_current_emitter(token)

    async def task_b():
        token = set_current_emitter(emitter_b)
        await report_activity("task B")
        reset_current_emitter(token)

    await asyncio.gather(
        asyncio.create_task(task_a()),
        asyncio.create_task(task_b()),
    )

    callback_a.assert_called_once_with("task A")
    callback_b.assert_called_once_with("task B")

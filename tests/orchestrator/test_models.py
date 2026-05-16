import asyncio
from datetime import datetime

import pytest

from common.models import TestStepResult
from orchestrator.models import MAX_STEP_SUMMARIES, TaskHistory, TaskRecord, TaskStatus


def _make_record(task_id: str = "t1") -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        agent_id="agent-1",
        agent_name="Test Agent",
        description="desc",
        status=TaskStatus.RUNNING,
        start_time=datetime.now(),
    )


def _make_step_result() -> TestStepResult:
    return TestStepResult(
        stepDescription="Click button",
        testData=[],
        expectedResults="Button is clicked",
        actualResults="Button was clicked",
        success=True,
        errorMessage="",
    )


# ---------------------------------------------------------------------------
# TaskRecord.to_dict round-trip for new fields
# ---------------------------------------------------------------------------


def test_to_dict_includes_new_fields_with_defaults():
    record = _make_record()
    d = record.to_dict()
    assert d["current_activity"] is None
    assert d["step_summaries"] == []
    assert d["step_results"] == []


def test_to_dict_round_trips_current_activity():
    record = _make_record()
    record.current_activity = "Fetching data"
    d = record.to_dict()
    assert d["current_activity"] == "Fetching data"


def test_to_dict_round_trips_step_summaries():
    record = _make_record()
    record.step_summaries = ["step 1", "step 2"]
    d = record.to_dict()
    assert d["step_summaries"] == ["step 1", "step 2"]


def test_to_dict_round_trips_step_results():
    record = _make_record()
    result = _make_step_result()
    record.step_results = [result]
    d = record.to_dict()
    assert len(d["step_results"]) == 1
    assert d["step_results"][0]["stepDescription"] == "Click button"
    assert d["step_results"][0]["success"] is True


# ---------------------------------------------------------------------------
# TaskHistory new mutators
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_current_activity():
    history = TaskHistory()
    record = _make_record()
    await history.add(record)
    await history.set_current_activity("t1", "Doing X")
    retrieved = await history.get_by_id("t1")
    assert retrieved.current_activity == "Doing X"


@pytest.mark.asyncio
async def test_clear_current_activity():
    history = TaskHistory()
    record = _make_record()
    record.current_activity = "Doing X"
    await history.add(record)
    await history.clear_current_activity("t1")
    retrieved = await history.get_by_id("t1")
    assert retrieved.current_activity is None


@pytest.mark.asyncio
async def test_append_step_summary():
    history = TaskHistory()
    await history.add(_make_record())
    await history.append_step_summary("t1", "summary 1")
    await history.append_step_summary("t1", "summary 2")
    retrieved = await history.get_by_id("t1")
    assert retrieved.step_summaries == ["summary 1", "summary 2"]


@pytest.mark.asyncio
async def test_append_step_summary_caps_at_max():
    history = TaskHistory()
    await history.add(_make_record())
    for i in range(MAX_STEP_SUMMARIES + 5):
        await history.append_step_summary("t1", f"summary {i}")
    retrieved = await history.get_by_id("t1")
    assert len(retrieved.step_summaries) == MAX_STEP_SUMMARIES
    # Oldest entries are dropped from the front
    assert retrieved.step_summaries[0] == f"summary {5}"


@pytest.mark.asyncio
async def test_append_step_result():
    history = TaskHistory()
    await history.add(_make_record())
    result = _make_step_result()
    await history.append_step_result("t1", result)
    retrieved = await history.get_by_id("t1")
    assert len(retrieved.step_results) == 1
    assert retrieved.step_results[0].stepDescription == "Click button"


@pytest.mark.asyncio
async def test_append_log_batch_initialises_none_logs():
    history = TaskHistory()
    record = _make_record()
    assert record.agent_logs is None
    await history.add(record)
    await history.append_log_batch("t1", ["log line 1", "log line 2"])
    retrieved = await history.get_by_id("t1")
    assert retrieved.agent_logs == ["log line 1", "log line 2"]


@pytest.mark.asyncio
async def test_append_log_batch_extends_existing_logs():
    history = TaskHistory()
    record = _make_record()
    record.agent_logs = ["existing"]
    await history.add(record)
    await history.append_log_batch("t1", ["new 1", "new 2"])
    retrieved = await history.get_by_id("t1")
    assert retrieved.agent_logs == ["existing", "new 1", "new 2"]


@pytest.mark.asyncio
async def test_mutators_noop_for_unknown_task_id():
    """All mutators must silently ignore unknown task IDs."""
    history = TaskHistory()
    await history.set_current_activity("unknown", "text")
    await history.clear_current_activity("unknown")
    await history.append_step_summary("unknown", "text")
    await history.append_step_result("unknown", _make_step_result())
    await history.append_log_batch("unknown", ["line"])


# ---------------------------------------------------------------------------
# Atomicity smoke test — 100 concurrent appends
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_step_summary_atomic_under_contention():
    history = TaskHistory()
    await history.add(_make_record())
    await asyncio.gather(*[history.append_step_summary("t1", f"s{i}") for i in range(100)])
    retrieved = await history.get_by_id("t1")
    assert len(retrieved.step_summaries) == 100


@pytest.mark.asyncio
async def test_append_step_result_atomic_under_contention():
    history = TaskHistory()
    await history.add(_make_record())
    await asyncio.gather(*[history.append_step_result("t1", _make_step_result()) for _ in range(100)])
    retrieved = await history.get_by_id("t1")
    assert len(retrieved.step_results) == 100

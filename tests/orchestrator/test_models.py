from datetime import datetime

import pytest

from orchestrator.models import TaskHistory, TaskRecord, TaskStatus


def _make_record(task_id: str = "t1") -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        agent_id="agent-1",
        agent_name="Test Agent",
        description="desc",
        status=TaskStatus.RUNNING,
        start_time=datetime.now(),
    )


# ---------------------------------------------------------------------------
# TaskRecord.to_dict round-trip
# ---------------------------------------------------------------------------


def test_to_dict_includes_current_activity_default():
    record = _make_record()
    d = record.to_dict()
    assert d["current_activity"] is None


def test_to_dict_round_trips_current_activity():
    record = _make_record()
    record.current_activity = "Fetching data"
    d = record.to_dict()
    assert d["current_activity"] == "Fetching data"


# ---------------------------------------------------------------------------
# TaskHistory mutators
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
    await history.append_log_batch("unknown", ["line"])

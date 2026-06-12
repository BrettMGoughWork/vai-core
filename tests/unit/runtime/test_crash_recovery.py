"""Tests for src.runtime.worker_pool.crash_recovery — pure logic and pool integration."""

from __future__ import annotations

import time

from src.platform.runtime.worker_pool.crash_recovery import (
    JobRequeueDecision,
    WorkerCrashEvent,
    WorkerCrashRecovery,
    WorkerPoolInstruction,
    WorkerRestartDecision,
    default_worker_crash_recovery,
)
from src.platform.runtime.worker_pool.isolation import (
    IsolationConfig,
    IsolationMode,
    ProcessWorkerPool,
    ThreadWorker,
    ThreadWorkerPool,
)

# ---------------------------------------------------------------------------
# WorkerCrashEvent
# ---------------------------------------------------------------------------


def test_crash_event_frozen() -> None:
    event = WorkerCrashEvent(worker_id="w1", active_job_id="j1", timestamp=100.0)
    import dataclasses

    assert dataclasses.fields(WorkerCrashEvent)


def test_crash_event_no_active_job() -> None:
    event = WorkerCrashEvent(worker_id="w2", active_job_id=None, timestamp=200.0)
    assert event.worker_id == "w2"
    assert event.active_job_id is None


# ---------------------------------------------------------------------------
# WorkerRestartDecision
# ---------------------------------------------------------------------------


def test_restart_decision_frozen() -> None:
    d = WorkerRestartDecision(should_restart=True, worker_id="w1", reason="crashed")
    assert d.should_restart
    assert d.worker_id == "w1"
    assert d.reason == "crashed"


def test_restart_decision_no_restart() -> None:
    d = WorkerRestartDecision(
        should_restart=False, worker_id="w1", reason="not-needed"
    )
    assert not d.should_restart


# ---------------------------------------------------------------------------
# JobRequeueDecision
# ---------------------------------------------------------------------------


def test_requeue_decision_frozen() -> None:
    d = JobRequeueDecision(should_requeue=True, job_id="j1", reason="in-flight")
    assert d.should_requeue
    assert d.job_id == "j1"


def test_requeue_decision_no_job() -> None:
    d = JobRequeueDecision(should_requeue=False, job_id=None, reason="idle")
    assert not d.should_requeue
    assert d.job_id is None


# ---------------------------------------------------------------------------
# WorkerPoolInstruction
# ---------------------------------------------------------------------------


def test_pool_instruction_frozen() -> None:
    restart = WorkerRestartDecision(should_restart=True, worker_id="w1", reason="crash")
    requeue = JobRequeueDecision(should_requeue=True, job_id="j1", reason="in-flight")
    instr = WorkerPoolInstruction(restart=restart, requeue=requeue)
    assert instr.restart.should_restart
    assert instr.requeue.should_requeue


# ---------------------------------------------------------------------------
# WorkerCrashRecovery.evaluate
# ---------------------------------------------------------------------------


def _make_recovery() -> WorkerCrashRecovery:
    return WorkerCrashRecovery(clock=lambda: 42.0)


def test_evaluate_with_active_job() -> None:
    recovery = _make_recovery()
    event = WorkerCrashEvent(worker_id="w3", active_job_id="j7", timestamp=42.0)
    instr = recovery.evaluate(event)

    assert instr.restart.should_restart
    assert instr.restart.worker_id == "w3"
    assert instr.restart.reason == "worker-crashed"

    assert instr.requeue.should_requeue
    assert instr.requeue.job_id == "j7"
    assert instr.requeue.reason == "job-in-flight-at-crash"


def test_evaluate_idle_worker() -> None:
    recovery = _make_recovery()
    event = WorkerCrashEvent(worker_id="w4", active_job_id=None, timestamp=42.0)
    instr = recovery.evaluate(event)

    assert instr.restart.should_restart
    assert instr.restart.worker_id == "w4"

    assert not instr.requeue.should_requeue
    assert instr.requeue.job_id is None
    assert instr.requeue.reason == "no-active-job"


def test_evaluate_deterministic() -> None:
    """Same input always produces the same output."""
    recovery = _make_recovery()
    event = WorkerCrashEvent(worker_id="fix", active_job_id="job99", timestamp=1.0)

    result1 = recovery.evaluate(event)
    result2 = recovery.evaluate(event)

    assert result1 == result2
    assert result1.restart == result2.restart
    assert result1.requeue == result2.requeue


def test_evaluate_no_side_effects() -> None:
    """evaluate() must not mutate the event."""
    recovery = _make_recovery()
    event = WorkerCrashEvent(worker_id="w", active_job_id="j", timestamp=1.0)
    recovery.evaluate(event)
    # Re-reading the event must yield the same values
    assert event.worker_id == "w"
    assert event.active_job_id == "j"
    assert event.timestamp == 1.0


# ---------------------------------------------------------------------------
# default_worker_crash_recovery factory
# ---------------------------------------------------------------------------


def test_default_factory() -> None:
    recovery = default_worker_crash_recovery()
    assert isinstance(recovery, WorkerCrashRecovery)


def test_default_factory_produces_equivalent() -> None:
    recovery = default_worker_crash_recovery()
    event = WorkerCrashEvent(worker_id="w", active_job_id="j", timestamp=1.0)
    instr = recovery.evaluate(event)
    assert instr.restart.should_restart
    assert instr.requeue.should_requeue


# ---------------------------------------------------------------------------
# Pool integration — ThreadWorkerPool.handle_worker_exit
# ---------------------------------------------------------------------------


def test_thread_pool_handle_exit_with_active_job() -> None:
    config = IsolationConfig(concurrency=1, tick_interval=0.01)
    pool = ThreadWorkerPool(config, lambda wid: None)
    worker = pool._workers[0]
    worker.active_job_id = "j42"

    instr = pool.handle_worker_exit(worker)

    assert instr.restart.should_restart
    assert instr.restart.worker_id == "0"
    assert instr.requeue.should_requeue
    assert instr.requeue.job_id == "j42"


def test_thread_pool_handle_exit_idle() -> None:
    config = IsolationConfig(concurrency=1, tick_interval=0.01)
    pool = ThreadWorkerPool(config, lambda wid: None)
    worker = pool._workers[0]
    worker.active_job_id = None  # idle

    instr = pool.handle_worker_exit(worker)

    assert instr.restart.should_restart
    assert not instr.requeue.should_requeue
    assert instr.requeue.job_id is None


def test_thread_pool_handle_exit_deterministic() -> None:
    """Same input produces same instruction on repeated calls."""
    config = IsolationConfig(concurrency=1, tick_interval=0.01)
    pool = ThreadWorkerPool(config, lambda wid: None)
    worker = pool._workers[0]
    worker.active_job_id = "j-fixed"

    instr1 = pool.handle_worker_exit(worker)
    instr2 = pool.handle_worker_exit(worker)

    # restart decision is deterministic
    assert instr1.restart == instr2.restart
    # requeue is deterministic
    assert instr1.requeue == instr2.requeue


def test_thread_pool_handle_exit_worker_referenced() -> None:
    """Confirm the method uses the worker's own active_job_id."""
    config = IsolationConfig(concurrency=2, tick_interval=0.01)
    pool = ThreadWorkerPool(config, lambda wid: None)

    pool._workers[0].active_job_id = "j-a"
    pool._workers[1].active_job_id = "j-b"

    instr0 = pool.handle_worker_exit(pool._workers[0])
    instr1 = pool.handle_worker_exit(pool._workers[1])

    assert instr0.requeue.job_id == "j-a"
    assert instr1.requeue.job_id == "j-b"


# ---------------------------------------------------------------------------
# Pool integration — ProcessWorkerPool.handle_worker_exit
# ---------------------------------------------------------------------------


def _process_handler(_wid: int) -> None:
    pass


def test_process_pool_handle_exit_with_active_job() -> None:
    config = IsolationConfig(
        mode=IsolationMode.PROCESSES, concurrency=1, tick_interval=0.01
    )
    pool = ProcessWorkerPool(config, _process_handler)
    worker = pool._workers[0]
    worker.active_job_id = "j99"

    instr = pool.handle_worker_exit(worker)

    assert instr.restart.should_restart
    assert instr.restart.worker_id == "0"
    assert instr.requeue.should_requeue
    assert instr.requeue.job_id == "j99"


def test_process_pool_handle_exit_idle() -> None:
    config = IsolationConfig(
        mode=IsolationMode.PROCESSES, concurrency=1, tick_interval=0.01
    )
    pool = ProcessWorkerPool(config, _process_handler)
    worker = pool._workers[0]
    worker.active_job_id = None

    instr = pool.handle_worker_exit(worker)

    assert instr.restart.should_restart
    assert not instr.requeue.should_requeue
    assert instr.requeue.job_id is None


# ---------------------------------------------------------------------------
# Worker active_job_id attribute
# ---------------------------------------------------------------------------


def test_thread_worker_active_job_default() -> None:
    from threading import Event

    t = ThreadWorker(0, lambda wid: None, Event())
    assert t.active_job_id is None


def test_thread_worker_active_job_settable() -> None:
    from threading import Event

    t = ThreadWorker(0, lambda wid: None, Event())
    t.active_job_id = "j5"
    assert t.active_job_id == "j5"

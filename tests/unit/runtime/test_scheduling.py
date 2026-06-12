"""Tests for src.runtime.scheduling — deterministic job scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.platform.runtime.config.runtime import SchedulingConfig
from src.platform.runtime.scheduling.policy import (
    JobMetadata,
    Scheduler,
    SchedulingContext,
    SchedulingDecision,
    SchedulingMode,
    create_scheduler,
)
from src.platform.runtime.worker_tick import (
    TickInstruction,
    run_scheduling_tick,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)


def _job(
    job_id: str,
    priority: int = 0,
    offset_minutes: int = 0,
) -> JobMetadata:
    return JobMetadata(
        job_id=job_id,
        priority=priority,
        created_at=_T0 + timedelta(minutes=offset_minutes),
    )


# ---------------------------------------------------------------------------
# SchedulingMode
# ---------------------------------------------------------------------------


def test_scheduling_mode_values() -> None:
    assert SchedulingMode.FIFO.value == "fifo"
    assert SchedulingMode.PRIORITY.value == "priority"


# ---------------------------------------------------------------------------
# SchedulingDecision
# ---------------------------------------------------------------------------


def test_decision_none() -> None:
    d = SchedulingDecision(job_id=None, reason="no-jobs")
    assert d.job_id is None
    assert d.reason == "no-jobs"


def test_decision_selected() -> None:
    d = SchedulingDecision(job_id="j1", reason="fifo")
    assert d.job_id == "j1"
    assert d.reason == "fifo"


# ---------------------------------------------------------------------------
# FIFO scheduling
# ---------------------------------------------------------------------------


def test_fifo_oldest_first() -> None:
    sched = Scheduler(SchedulingMode.FIFO)
    jobs = [
        _job("j3", offset_minutes=5),
        _job("j1", offset_minutes=0),
        _job("j2", offset_minutes=2),
    ]
    decision = sched.select(SchedulingContext(pending_jobs=jobs))
    assert decision.job_id == "j1"
    assert decision.reason is not None and decision.reason.startswith("fifo:")


def test_fifo_tie_break_by_job_id() -> None:
    sched = Scheduler(SchedulingMode.FIFO)
    jobs = [
        _job("b", offset_minutes=0),
        _job("a", offset_minutes=0),
    ]
    decision = sched.select(SchedulingContext(pending_jobs=jobs))
    assert decision.job_id == "a"  # lexicographically first


def test_fifo_empty() -> None:
    sched = Scheduler(SchedulingMode.FIFO)
    decision = sched.select(SchedulingContext(pending_jobs=[]))
    assert decision.job_id is None
    assert decision.reason == "no-jobs"


def test_fifo_single_job() -> None:
    sched = Scheduler(SchedulingMode.FIFO)
    jobs = [_job("only", offset_minutes=0)]
    decision = sched.select(SchedulingContext(pending_jobs=jobs))
    assert decision.job_id == "only"


# ---------------------------------------------------------------------------
# PRIORITY scheduling
# ---------------------------------------------------------------------------


def test_priority_highest_first() -> None:
    sched = Scheduler(SchedulingMode.PRIORITY)
    jobs = [
        _job("low", priority=1, offset_minutes=0),
        _job("high", priority=10, offset_minutes=5),
        _job("mid", priority=5, offset_minutes=2),
    ]
    decision = sched.select(SchedulingContext(pending_jobs=jobs))
    assert decision.job_id == "high"


def test_priority_tie_break_by_age() -> None:
    sched = Scheduler(SchedulingMode.PRIORITY)
    jobs = [
        _job("young", priority=10, offset_minutes=5),
        _job("old", priority=10, offset_minutes=0),
    ]
    decision = sched.select(SchedulingContext(pending_jobs=jobs))
    assert decision.job_id == "old"


def test_priority_tie_break_by_job_id() -> None:
    sched = Scheduler(SchedulingMode.PRIORITY)
    jobs = [
        _job("x", priority=10, offset_minutes=0),
        _job("y", priority=10, offset_minutes=0),
    ]
    decision = sched.select(SchedulingContext(pending_jobs=jobs))
    # Both same priority & age → lexicographic by job_id
    assert decision.job_id == "x"


def test_priority_empty() -> None:
    sched = Scheduler(SchedulingMode.PRIORITY)
    decision = sched.select(SchedulingContext(pending_jobs=[]))
    assert decision.job_id is None
    assert decision.reason == "no-jobs"


def test_priority_reason_contains_priority() -> None:
    sched = Scheduler(SchedulingMode.PRIORITY)
    jobs = [_job("j", priority=42, offset_minutes=0)]
    decision = sched.select(SchedulingContext(pending_jobs=jobs))
    assert decision.job_id == "j"
    assert decision.reason is not None
    assert "42" in decision.reason


# ---------------------------------------------------------------------------
# create_scheduler factory
# ---------------------------------------------------------------------------


def test_create_scheduler_fifo() -> None:
    sched = create_scheduler(SchedulingMode.FIFO)
    assert isinstance(sched, Scheduler)
    assert sched.mode == SchedulingMode.FIFO


def test_create_scheduler_priority() -> None:
    sched = create_scheduler(SchedulingMode.PRIORITY)
    assert isinstance(sched, Scheduler)
    assert sched.mode == SchedulingMode.PRIORITY


# ---------------------------------------------------------------------------
# SchedulingConfig
# ---------------------------------------------------------------------------


def test_scheduling_config_defaults() -> None:
    cfg = SchedulingConfig()
    assert cfg.scheduling_mode == SchedulingMode.FIFO


def test_scheduling_config_custom() -> None:
    cfg = SchedulingConfig(scheduling_mode=SchedulingMode.PRIORITY)
    assert cfg.scheduling_mode == SchedulingMode.PRIORITY


# ---------------------------------------------------------------------------
# TickInstruction
# ---------------------------------------------------------------------------


def test_tick_no_work() -> None:
    inst = TickInstruction.no_work(reason="queue-empty")
    assert inst.action == "no_work"
    assert inst.job_id is None
    assert inst.reason == "queue-empty"


def test_tick_claim_job() -> None:
    inst = TickInstruction.claim_job(job_id="j1", reason="fifo:selected")
    assert inst.action == "claim_job"
    assert inst.job_id == "j1"
    assert inst.reason == "fifo:selected"


# ---------------------------------------------------------------------------
# run_scheduling_tick integration
# ---------------------------------------------------------------------------


def test_run_scheduling_tick_selects_job() -> None:
    sched = create_scheduler(SchedulingMode.FIFO)
    jobs = [
        _job("alpha", offset_minutes=0),
        _job("beta", offset_minutes=1),
    ]
    inst = run_scheduling_tick(sched, jobs)
    assert inst.action == "claim_job"
    assert inst.job_id == "alpha"
    assert inst.reason is not None and inst.reason.startswith("fifo:")


def test_run_scheduling_tick_no_work() -> None:
    sched = create_scheduler(SchedulingMode.PRIORITY)
    inst = run_scheduling_tick(sched, [])
    assert inst.action == "no_work"
    assert inst.job_id is None
    assert inst.reason == "no-jobs"


def test_run_scheduling_tick_deterministic() -> None:
    """Same inputs always produce the same output."""
    sched = create_scheduler(SchedulingMode.FIFO)
    jobs = [
        _job("b", offset_minutes=5),
        _job("a", offset_minutes=5),
        _job("c", offset_minutes=2),
    ]
    result_1 = run_scheduling_tick(sched, jobs)
    result_2 = run_scheduling_tick(sched, jobs)
    assert result_1.job_id == result_2.job_id
    assert result_1.reason == result_2.reason


# ---------------------------------------------------------------------------
# Scheduler determinism (pure logic guarantees)
# ---------------------------------------------------------------------------


def test_scheduler_does_not_mutate_input() -> None:
    sched = Scheduler(SchedulingMode.FIFO)
    jobs = [
        _job("j1", offset_minutes=5),
        _job("j2", offset_minutes=0),
    ]
    original_ids = [j.job_id for j in jobs]
    sched.select(SchedulingContext(pending_jobs=jobs))
    assert [j.job_id for j in jobs] == original_ids


def test_scheduler_deterministic_across_calls() -> None:
    sched = Scheduler(SchedulingMode.PRIORITY)
    jobs = [
        _job("a", priority=10, offset_minutes=0),
        _job("b", priority=5, offset_minutes=1),
        _job("c", priority=10, offset_minutes=0),
    ]
    d1 = sched.select(SchedulingContext(pending_jobs=jobs))
    d2 = sched.select(SchedulingContext(pending_jobs=jobs))
    assert d1.job_id == d2.job_id
    assert d1.reason == d2.reason

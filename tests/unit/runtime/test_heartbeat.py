"""Tests for S4.5.4 heartbeat subsystem — pure logic, no IO, no backend."""

from __future__ import annotations

import time

from src.platform.runtime.config.runtime import HeartbeatConfig
from src.platform.runtime.heartbeat.control_plane import HeartbeatMonitor, HeartbeatStatus
from src.platform.runtime.heartbeat.emitter import HeartbeatEmitter
from src.platform.runtime.heartbeat.events import HeartbeatEvent
from src.platform.runtime.worker_tick import (
    TickInstruction,
    run_heartbeat_tick,
)

# ---------------------------------------------------------------------------
# HeartbeatEvent — immutable data
# ---------------------------------------------------------------------------


def test_heartbeat_event_immutable() -> None:
    e = HeartbeatEvent(
        worker_id="w1",
        timestamp=100.0,
        active_job_id="j1",
        cycles_completed=42,
        health="busy",
    )
    assert e.worker_id == "w1"
    assert e.timestamp == 100.0
    assert e.active_job_id == "j1"
    assert e.cycles_completed == 42
    assert e.health == "busy"


def test_heartbeat_event_idle() -> None:
    e = HeartbeatEvent(
        worker_id="w2",
        timestamp=200.0,
        active_job_id=None,
        cycles_completed=0,
        health="idle",
    )
    assert e.active_job_id is None
    assert e.health == "idle"


# ---------------------------------------------------------------------------
# HeartbeatEmitter — deterministic event construction
# ---------------------------------------------------------------------------


def test_emitter_uses_clock() -> None:
    calls: list[float] = []

    def fake_clock() -> float:
        calls.append(42.0)
        return 42.0

    emitter = HeartbeatEmitter(worker_id="w1", clock=fake_clock)
    event = emitter.emit(active_job_id=None, cycles_completed=0, health="idle")
    assert event.timestamp == 42.0
    assert len(calls) == 1


def test_emitter_default_clock() -> None:
    emitter = HeartbeatEmitter(worker_id="w1")
    before = time.time()
    event = emitter.emit(active_job_id=None, cycles_completed=0, health="idle")
    after = time.time()
    assert before <= event.timestamp <= after


def test_emitter_passes_fields() -> None:
    emitter = HeartbeatEmitter(worker_id="w1", clock=lambda: 10.0)
    event = emitter.emit(active_job_id="j99", cycles_completed=7, health="busy")
    assert event.worker_id == "w1"
    assert event.active_job_id == "j99"
    assert event.cycles_completed == 7
    assert event.health == "busy"
    assert event.timestamp == 10.0


# ---------------------------------------------------------------------------
# HeartbeatMonitor — tracking and health classification
# ---------------------------------------------------------------------------


def test_monitor_update_records_and_returns_healthy() -> None:
    mon = HeartbeatMonitor(timeout_seconds=5.0)
    event = HeartbeatEvent("w1", 100.0, None, 0, "idle")
    status = mon.update(event, now=101.0)
    assert status.worker_id == "w1"
    assert status.last_seen == 100.0
    assert status.is_healthy is True  # 1s elapsed, timeout is 5s
    assert mon.last_seen["w1"] == 100.0


def test_monitor_update_unhealthy() -> None:
    mon = HeartbeatMonitor(timeout_seconds=5.0)
    event = HeartbeatEvent("w1", 100.0, None, 0, "idle")
    status = mon.update(event, now=110.0)
    assert status.is_healthy is False  # 10s elapsed, timeout is 5s
    assert status.reason is not None
    assert "timeout" in status.reason


def test_monitor_default_now_uses_event_timestamp() -> None:
    mon = HeartbeatMonitor(timeout_seconds=5.0)
    event = HeartbeatEvent("w1", 100.0, None, 0, "idle")
    status = mon.update(event)  # no explicit now
    assert status.is_healthy is True  # elapsed = 100 - 100 = 0


def test_monitor_evaluate_all_workers() -> None:
    mon = HeartbeatMonitor(timeout_seconds=3.0)
    mon.last_seen["w1"] = 100.0
    mon.last_seen["w2"] = 102.0

    statuses = mon.evaluate(now=104.0)
    assert len(statuses) == 2

    by_id = {s.worker_id: s for s in statuses}
    assert by_id["w1"].is_healthy is False  # 4s elapsed
    assert by_id["w2"].is_healthy is True  # 2s elapsed


def test_monitor_evaluate_empty() -> None:
    mon = HeartbeatMonitor(timeout_seconds=5.0)
    assert mon.evaluate(now=100.0) == []


# ---------------------------------------------------------------------------
# HeartbeatStatus
# ---------------------------------------------------------------------------


def test_heartbeat_status_healthy() -> None:
    s = HeartbeatStatus(worker_id="w1", last_seen=10.0, is_healthy=True, reason="ok")
    assert s.worker_id == "w1"
    assert s.is_healthy is True
    assert s.reason == "ok"


def test_heartbeat_status_unhealthy() -> None:
    s = HeartbeatStatus(
        worker_id="w2",
        last_seen=5.0,
        is_healthy=False,
        reason="last_seen 10.0s ago (timeout 5s)",
    )
    assert s.is_healthy is False


# ---------------------------------------------------------------------------
# HeartbeatConfig
# ---------------------------------------------------------------------------


def test_heartbeat_config_defaults() -> None:
    cfg = HeartbeatConfig()
    assert cfg.interval_seconds == 1.0
    assert cfg.timeout_seconds == 5.0


def test_heartbeat_config_custom() -> None:
    cfg = HeartbeatConfig(interval_seconds=0.5, timeout_seconds=3.0)
    assert cfg.interval_seconds == 0.5
    assert cfg.timeout_seconds == 3.0


# ---------------------------------------------------------------------------
# TickInstruction heartbeat
# ---------------------------------------------------------------------------


def test_tick_heartbeat() -> None:
    event = HeartbeatEvent("w1", 100.0, "j1", 5, "busy")
    inst = TickInstruction.heartbeat(event)
    assert inst.action == "heartbeat"
    assert inst.job_id == "j1"
    assert inst.reason == "heartbeat"
    assert inst.event is event


def test_tick_heartbeat_idle() -> None:
    event = HeartbeatEvent("w2", 200.0, None, 0, "idle")
    inst = TickInstruction.heartbeat(event)
    assert inst.action == "heartbeat"
    assert inst.job_id is None
    assert inst.event is not None
    assert inst.event.worker_id == "w2"


# ---------------------------------------------------------------------------
# run_heartbeat_tick integration
# ---------------------------------------------------------------------------


def test_run_heartbeat_tick_busy() -> None:
    emitter = HeartbeatEmitter(worker_id="w1", clock=lambda: 100.0)
    inst = run_heartbeat_tick(emitter, active_job_id="j1", cycles_completed=5, health="busy")
    assert inst.action == "heartbeat"
    assert inst.job_id == "j1"
    assert inst.event is not None
    assert inst.event.worker_id == "w1"
    assert inst.event.timestamp == 100.0
    assert inst.event.cycles_completed == 5
    assert inst.event.health == "busy"


def test_run_heartbeat_tick_idle() -> None:
    emitter = HeartbeatEmitter(worker_id="w2", clock=lambda: 200.0)
    inst = run_heartbeat_tick(emitter, active_job_id=None, cycles_completed=0, health="idle")
    assert inst.action == "heartbeat"
    assert inst.job_id is None
    assert inst.event is not None
    assert inst.event.health == "idle"


# ---------------------------------------------------------------------------
# Determinism guarantees
# ---------------------------------------------------------------------------


def test_heartbeat_deterministic_with_fake_clock() -> None:
    """Same inputs always produce the same heartbeat event."""
    emitter = HeartbeatEmitter(worker_id="w1", clock=lambda: 123.456)
    inst1 = run_heartbeat_tick(emitter, "j1", 10, "busy")
    emitter2 = HeartbeatEmitter(worker_id="w1", clock=lambda: 123.456)
    inst2 = run_heartbeat_tick(emitter2, "j1", 10, "busy")
    assert inst1.event == inst2.event
    assert inst1.job_id == inst2.job_id


def test_monitor_deterministic() -> None:
    m1 = HeartbeatMonitor(timeout_seconds=5.0)
    m2 = HeartbeatMonitor(timeout_seconds=5.0)

    event = HeartbeatEvent("w1", 100.0, None, 0, "idle")
    s1 = m1.update(event, now=103.0)
    s2 = m2.update(event, now=103.0)

    assert s1 == s2

"""Tests for src.runtime.worker_pool.isolation — thread / process backends."""

from __future__ import annotations

import time
from multiprocessing import Event as ProcessEvent
from threading import Event as ThreadEvent

from src.platform.runtime.config.runtime import RuntimeConcurrencyConfig
from src.platform.runtime.worker_pool.isolation import (
    IsolationConfig,
    IsolationMode,
    ProcessWorker,
    ProcessWorkerPool,
    ThreadWorker,
    ThreadWorkerPool,
    WorkerPoolFactory,
)


# ---------------------------------------------------------------------------
# Module-level handlers (must be pickleable for ProcessWorker tests)
# ---------------------------------------------------------------------------

_tracker: list[int] = []


def _reset_tracker() -> None:
    _tracker.clear()


def _tracking_handler(worker_id: int) -> None:
    _tracker.append(worker_id)


# ---------------------------------------------------------------------------
# IsolationMode
# ---------------------------------------------------------------------------


def test_isolation_mode_values() -> None:
    assert IsolationMode.THREADS.value == "threads"
    assert IsolationMode.PROCESSES.value == "processes"


def test_isolation_mode_uniqueness() -> None:
    assert IsolationMode.THREADS != IsolationMode.PROCESSES


# ---------------------------------------------------------------------------
# IsolationConfig
# ---------------------------------------------------------------------------


def test_isolation_config_defaults() -> None:
    cfg = IsolationConfig()
    assert cfg.mode == IsolationMode.THREADS
    assert cfg.concurrency == 1
    assert cfg.tick_interval == 0.05


def test_isolation_config_custom() -> None:
    cfg = IsolationConfig(
        mode=IsolationMode.PROCESSES,
        concurrency=4,
        tick_interval=0.1,
    )
    assert cfg.mode == IsolationMode.PROCESSES
    assert cfg.concurrency == 4
    assert cfg.tick_interval == 0.1


# ---------------------------------------------------------------------------
# ThreadWorker
# ---------------------------------------------------------------------------


def test_thread_worker_stops_on_event() -> None:
    called: list[int] = []
    stop = ThreadEvent()

    def handler(wid: int) -> None:
        called.append(wid)
        stop.set()  # stop after first tick

    t = ThreadWorker(
        worker_id=7,
        handler=handler,
        stop_event=stop,
        tick_interval=0.001,
    )
    t.start()
    t.join(timeout=2)
    assert not t.is_alive()
    assert 7 in called


def test_thread_worker_daemon_flag() -> None:
    stop = ThreadEvent()
    t = ThreadWorker(
        worker_id=0,
        handler=lambda wid: None,
        stop_event=stop,
    )
    assert t.daemon is True


# ---------------------------------------------------------------------------
# ProcessWorker
# ---------------------------------------------------------------------------


def test_process_worker_stops_on_event() -> None:
    """Process worker starts, runs for a tick, then stops cleanly.

    On Windows with ``spawn`` the child runs in a fresh interpreter, so we
    cannot observe child-side global state from the parent.  We verify
    lifecycle (start → stop → not alive) instead.
    """
    stop = ProcessEvent()

    p = ProcessWorker(
        worker_id=3,
        handler=_tracking_handler,
        stop_event=stop,
        tick_interval=0.001,
    )
    p.start()
    time.sleep(0.1)  # let it spin a few ticks
    assert p.is_alive()
    stop.set()
    p.join(timeout=3)
    assert not p.is_alive()


def test_process_worker_daemon_flag() -> None:
    stop = ProcessEvent()
    p = ProcessWorker(
        worker_id=0,
        handler=_tracking_handler,
        stop_event=stop,
    )
    assert p.daemon is True


# ---------------------------------------------------------------------------
# ThreadWorkerPool — lifecycle
# ---------------------------------------------------------------------------


def test_thread_pool_start_stop() -> None:
    called: list[int] = []
    stop = ThreadEvent()

    def handler(wid: int) -> None:
        called.append(wid)
        stop.set()

    config = IsolationConfig(concurrency=2, tick_interval=0.002)
    pool = ThreadWorkerPool(config, handler)
    pool.start()
    stop.wait(timeout=2)
    pool.stop()
    pool.join()

    assert pool.worker_count == 2
    assert len(called) >= 2


def test_thread_pool_worker_count() -> None:
    config = IsolationConfig(concurrency=4)
    pool = ThreadWorkerPool(config, lambda wid: None)
    assert pool.worker_count == 4


def test_thread_pool_stop_idempotent() -> None:
    config = IsolationConfig(concurrency=1, tick_interval=0.01)
    pool = ThreadWorkerPool(config, lambda wid: None)
    pool.start()
    pool.stop()
    pool.stop()  # must not raise
    pool.join()


def test_thread_pool_clean_shutdown() -> None:
    config = IsolationConfig(concurrency=3, tick_interval=0.01)
    pool = ThreadWorkerPool(config, lambda wid: None)
    pool.start()
    pool.stop()
    pool.join()
    for w in pool._workers:
        assert not w.is_alive()


# ---------------------------------------------------------------------------
# ProcessWorkerPool — lifecycle
# ---------------------------------------------------------------------------


def test_process_pool_start_stop() -> None:
    """Process pool starts, runs, then stops cleanly.

    Lifecycle verification only — see note in
    :func:`test_process_worker_stops_on_event`.
    """
    config = IsolationConfig(
        mode=IsolationMode.PROCESSES,
        concurrency=2,
        tick_interval=0.002,
    )
    pool = ProcessWorkerPool(config, _tracking_handler)
    pool.start()
    time.sleep(0.1)
    assert pool.worker_count == 2
    pool.stop()
    pool.join()
    for w in pool._workers:
        assert not w.is_alive()


def test_process_pool_worker_count() -> None:
    config = IsolationConfig(mode=IsolationMode.PROCESSES, concurrency=4)
    pool = ProcessWorkerPool(config, _tracking_handler)
    assert pool.worker_count == 4


def test_process_pool_clean_shutdown() -> None:
    config = IsolationConfig(
        mode=IsolationMode.PROCESSES,
        concurrency=2,
        tick_interval=0.01,
    )
    pool = ProcessWorkerPool(config, _tracking_handler)
    pool.start()
    pool.stop()
    pool.join()
    for w in pool._workers:
        assert not w.is_alive()


# ---------------------------------------------------------------------------
# WorkerPoolFactory — dispatch
# ---------------------------------------------------------------------------


def test_factory_creates_thread_pool() -> None:
    config = IsolationConfig(mode=IsolationMode.THREADS, concurrency=2)
    pool = WorkerPoolFactory.create(config, lambda wid: None)
    assert isinstance(pool, ThreadWorkerPool)
    assert pool.worker_count == 2


def test_factory_creates_process_pool() -> None:
    config = IsolationConfig(
        mode=IsolationMode.PROCESSES,
        concurrency=3,
        tick_interval=0.01,
    )
    pool = WorkerPoolFactory.create(config, _tracking_handler)
    assert isinstance(pool, ProcessWorkerPool)
    assert pool.worker_count == 3


def test_factory_invalid_mode() -> None:
    class FakeMode:
        value = "unknown"

    config = IsolationConfig(mode=FakeMode())  # type: ignore[arg-type]
    try:
        WorkerPoolFactory.create(config, lambda wid: None)
        assert False, "Expected ValueError"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# RuntimeConcurrencyConfig
# ---------------------------------------------------------------------------


def test_runtime_config_defaults() -> None:
    cfg = RuntimeConcurrencyConfig()
    assert cfg.isolation == IsolationMode.THREADS
    assert cfg.concurrency == 1
    assert cfg.tick_interval == 0.05


def test_runtime_config_custom() -> None:
    cfg = RuntimeConcurrencyConfig(
        isolation=IsolationMode.PROCESSES,
        concurrency=8,
        tick_interval=0.5,
    )
    assert cfg.isolation == IsolationMode.PROCESSES
    assert cfg.concurrency == 8
    assert cfg.tick_interval == 0.5


# ---------------------------------------------------------------------------
# Integration — worker_entrypoint
# ---------------------------------------------------------------------------


def test_run_worker_pool_with_runtime_config() -> None:
    """Entrypoint accepts RuntimeConcurrencyConfig and starts cleanly."""
    from src.platform.runtime.worker_entrypoint import run_worker_pool

    cfg = RuntimeConcurrencyConfig(
        isolation=IsolationMode.THREADS,
        concurrency=1,
        tick_interval=0.005,
    )
    # Run in a daemon thread — KeyboardInterrupt in a worker doesn't
    # propagate to the main thread, so we start and immediately stop via
    # the daemon thread's termination on test exit.
    import threading

    pool_thread = threading.Thread(
        target=run_worker_pool,
        args=(cfg,),
        daemon=True,
    )
    pool_thread.start()
    time.sleep(0.06)  # enough for at least one tick
    # No assertion needed beyond not hanging — the factory + pool are
    # exhaustively tested above; this validates the wiring
    assert pool_thread.is_alive()


def test_run_worker_pool_defaults() -> None:
    """Entrypoint runs with no config (defaults to RuntimeConcurrencyConfig)."""
    from src.platform.runtime.worker_entrypoint import run_worker_pool

    import threading

    pool_thread = threading.Thread(
        target=run_worker_pool,
        daemon=True,
    )
    pool_thread.start()
    time.sleep(0.06)
    assert pool_thread.is_alive()

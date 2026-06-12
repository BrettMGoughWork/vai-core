"""Tests for src.runtime.worker_pool."""

from __future__ import annotations

import time
from threading import Event

from src.platform.runtime.worker_pool.pool import (
    WorkerPool,
    WorkerPoolConfig,
    WorkerThread,
    create_worker_pool,
)


# ---------------------------------------------------------------------------
# WorkerThread
# ---------------------------------------------------------------------------


def test_worker_thread_stops_on_event() -> None:
    called: list[int] = []
    stop = Event()

    def handler(wid: int) -> None:
        called.append(wid)
        stop.set()  # stop after first tick

    t = WorkerThread(worker_id=7, handler=handler, stop_event=stop, tick_interval=0.001)
    t.start()
    t.join(timeout=2)
    assert not t.is_alive()
    assert 7 in called


def test_worker_thread_daemon_flag() -> None:
    stop = Event()
    t = WorkerThread(worker_id=0, handler=lambda wid: None, stop_event=stop)
    assert t.daemon is True


# ---------------------------------------------------------------------------
# WorkerPool
# ---------------------------------------------------------------------------


def test_pool_start_stop() -> None:
    calls: list[int] = []
    lock = _Lock()
    ran = Event()

    def handler(wid: int) -> None:
        with lock:
            calls.append(wid)
            ran.set()

    pool = WorkerPool(concurrency=2, handler=handler, tick_interval=0.005)
    pool.start()
    ran.wait(timeout=2)
    pool.stop()
    pool.join()

    assert pool.worker_count == 2
    # At least one call per worker
    assert len(calls) >= 2


def test_pool_worker_count_property() -> None:
    pool = WorkerPool(concurrency=4, handler=lambda wid: None)
    assert pool.worker_count == 4
    assert pool.worker_count == 4  # idempotent


def test_pool_stop_is_idempotent() -> None:
    pool = WorkerPool(concurrency=1, handler=lambda wid: None, tick_interval=0.01)
    pool.start()
    pool.stop()
    pool.stop()  # second call must not raise
    pool.join()


def test_pool_clean_shutdown() -> None:
    """Workers exit promptly after stop()."""
    pool = WorkerPool(concurrency=3, handler=lambda wid: None, tick_interval=0.5)
    pool.start()
    pool.stop()
    pool.join()
    for w in pool._workers:
        assert not w.is_alive()


# ---------------------------------------------------------------------------
# create_worker_pool factory
# ---------------------------------------------------------------------------


def test_create_worker_pool_defaults() -> None:
    config = WorkerPoolConfig(worker_handler=lambda wid: None)
    pool = create_worker_pool(config)
    assert isinstance(pool, WorkerPool)
    assert pool.worker_count == 1


def test_create_worker_pool_custom_concurrency() -> None:
    config = WorkerPoolConfig(
        worker_concurrency=5,
        worker_handler=lambda wid: None,
    )
    pool = create_worker_pool(config)
    assert pool.worker_count == 5


# ---------------------------------------------------------------------------
# WorkerPoolConfig
# ---------------------------------------------------------------------------


def test_config_defaults() -> None:
    cfg = WorkerPoolConfig()
    assert cfg.worker_concurrency == 1
    assert cfg.worker_tick_interval == 0.05
    assert cfg.worker_handler is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Lock:
    """Minimal threading lock for test synchronisation."""

    def __init__(self) -> None:
        from threading import Lock as _LockImpl
        self._lock = _LockImpl()

    def __enter__(self) -> None:
        self._lock.acquire()

    def __exit__(self, *args: object) -> None:
        self._lock.release()

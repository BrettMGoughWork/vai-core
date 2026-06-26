"""Decomposition worker pool — N daemon threads sharing one queue.

Each worker thread runs ``Worker.process_next()`` in a tight loop, popping
the next available decomposition job (subtask or continuation) from the shared
``InMemoryQueue``.  The pool replaces the single sequential ``Worker``
instance, enabling true parallel execution of subtask jobs.
"""

from __future__ import annotations

import atexit
import os
import threading
from collections.abc import Callable
from typing import Any

from src.platform.runtime.worker import Worker


def _default_pool_size() -> int:
    """Return the pool size from ``VAI_DECOMPOSITION_POOL_SIZE`` or a default."""
    raw = os.environ.get("VAI_DECOMPOSITION_POOL_SIZE", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    # Default: 2 workers (conservative; subtask workers are LLM-bound)
    return 2


class DecompositionWorkerPool:
    """Manages N daemon worker threads sharing one decomposition queue.

    Each thread runs a private ``Worker`` instance (sharing the same queue,
    control plane, executor, and ``on_job_complete`` callback) and loops
    calling ``process_next()`` until the pool is stopped.

    Args:
        worker_factory:  Callable ``() -> Worker`` that creates a new worker
                         instance bound to the shared resources.
        pool_size:       Number of daemon threads.  Defaults to
                         ``VAI_DECOMPOSITION_POOL_SIZE`` env var or 2.
    """

    def __init__(
        self,
        worker_factory: Callable[[], Worker],
        pool_size: int | None = None,
    ) -> None:
        self._worker_factory = worker_factory
        self._pool_size = pool_size if pool_size is not None else _default_pool_size()
        self._threads: list[threading.Thread] = []
        self._stop_event = threading.Event()

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the pool — spawn N daemon worker threads."""
        if self._threads:
            return  # already started

        for i in range(self._pool_size):
            worker = self._worker_factory()
            thread = threading.Thread(
                target=_worker_loop,
                args=(worker, self._stop_event),
                name=f"decomp-worker-{i}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def stop(self, timeout: float = 5.0) -> None:
        """Signal all threads to stop and wait for them to finish."""
        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads.clear()

    @property
    def pool_size(self) -> int:
        """Return the configured number of worker threads."""
        return self._pool_size

    @property
    def is_running(self) -> bool:
        """Return ``True`` if at least one thread is alive."""
        return any(t.is_alive() for t in self._threads)


def _worker_loop(
    worker: Worker,
    stop_event: threading.Event,
) -> None:
    """Daemon loop: call ``worker.process_next()`` until stop is signalled.

    Sleeps briefly when the queue is empty so the thread doesn't busy-spin.
    """
    import time as _time

    while not stop_event.is_set():
        try:
            result = worker.process_next()
        except Exception:
            # Worker.process_next already handles exceptions internally
            # via the pipeline and top-level guards.  This is a safety net
            # to keep the thread alive in case of unexpected failures.
            result = None
        if result is None:
            # Queue was empty — yield CPU to avoid busy-spinning
            _time.sleep(0.01)

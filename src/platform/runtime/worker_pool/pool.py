"""Worker pool — deterministic concurrency for Stratum-4.

Thread-based worker pool with configurable concurrency, clean shutdown,
and stateless handler dispatch.  No queue operations, no JobStore writes,
no supervision, no durable semantics.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Event, Thread
from typing import Callable


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class WorkerPoolConfig:
    """Configuration for a :class:`WorkerPool`.

    Attributes:
        worker_concurrency: Number of worker threads to spawn.
        worker_tick_interval: Sleep interval (seconds) between handler
            invocations when no work is available.
        worker_handler: Callable invoked by each worker on every tick.
            Signature ``(worker_id: int) -> None``.  Must be stateless
            and idempotent.
    """

    worker_concurrency: int = 1
    worker_tick_interval: float = 0.05
    worker_handler: Callable | None = None


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------


class WorkerThread(Thread):
    """A single worker that repeatedly invokes *handler* until stopped.

    Args:
        worker_id: Numeric identifier for this worker.
        handler: Callable invoked on each tick (must be stateless).
        stop_event: Shared :class:`~threading.Event` signalled by the
            pool coordinator to request shutdown.
        tick_interval: Sleep gap between handler invocations.
    """

    def __init__(
        self,
        worker_id: int,
        handler: Callable,
        stop_event: Event,
        tick_interval: float = 0.05,
    ) -> None:
        super().__init__(name=f"worker-{worker_id}", daemon=True)
        self.worker_id = worker_id
        self._handler = handler
        self._stop_event = stop_event
        self._tick_interval = tick_interval

    def run(self) -> None:
        """Loop until *stop_event* is set, calling *handler* each tick."""
        while not self._stop_event.is_set():
            self._handler(self.worker_id)
            time.sleep(self._tick_interval)


# ---------------------------------------------------------------------------
# Pool coordinator
# ---------------------------------------------------------------------------


class WorkerPool:
    """Manages *concurrency* identical worker threads.

    Workers share only a :class:`~threading.Event` for shutdown signalling
    and the immutable configuration.  The handler *must* be stateless
    and idempotent.

    Args:
        concurrency: Number of worker threads.
        handler: Callable executed by each worker on every tick.
        tick_interval: Sleep gap between handler invocations (seconds).
    """

    def __init__(
        self,
        concurrency: int,
        handler: Callable,
        tick_interval: float = 0.05,
    ) -> None:
        self._concurrency = concurrency
        self._handler = handler
        self._tick_interval = tick_interval
        self._stop_event = Event()
        self._workers: list[WorkerThread] = [
            WorkerThread(i, handler, self._stop_event, tick_interval)
            for i in range(concurrency)
        ]

    # -- Lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Start all worker threads."""
        for w in self._workers:
            w.start()

    def stop(self) -> None:
        """Signal all workers to shut down."""
        self._stop_event.set()

    def join(self) -> None:
        """Wait for all worker threads to finish."""
        for w in self._workers:
            w.join()

    # -- Read-only property ------------------------------------------------

    @property
    def worker_count(self) -> int:
        """Return the configured number of workers."""
        return self._concurrency


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_worker_pool(config: WorkerPoolConfig) -> WorkerPool:
    """Build a :class:`WorkerPool` from *config*.

    Args:
        config: A :class:`WorkerPoolConfig` instance.

    Returns:
        A configured :class:`WorkerPool` ready for ``.start()``.
    """
    return WorkerPool(
        concurrency=config.worker_concurrency,
        handler=config.worker_handler,
        tick_interval=config.worker_tick_interval,
    )

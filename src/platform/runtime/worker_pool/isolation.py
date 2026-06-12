"""Thread / Process isolation for the Stratum-4 Worker Pool.

Provides a uniform ``{start, stop, join, worker_count}`` lifecycle across
both ``threading`` and ``multiprocessing`` backends.  The handler *must* be
stateless, idempotent, and (for process mode) pickleable.

Purity guarantees
-----------------
- **Thread mode** — handler inputs are treated as immutable; no shared
  mutable state beyond the stop event and config.
- **Process mode** — the pickle boundary naturally deep-copies all inputs,
  preventing accidental state leakage across workers.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from multiprocessing import Event as ProcessEvent
from multiprocessing import Process
from threading import Event as ThreadEvent
from threading import Thread
from typing import Callable

from src.platform.runtime.worker_pool.crash_recovery import (
    WorkerCrashEvent,
    WorkerCrashRecovery,
    WorkerPoolInstruction,
    default_worker_crash_recovery,
)


# ---------------------------------------------------------------------------
# Enum & config
# ---------------------------------------------------------------------------


class IsolationMode(Enum):
    """Backend selection for worker isolation.

    Attributes:
        THREADS:   Lightweight threads; fast spawning, shared address space.
        PROCESSES: Isolated processes; safe for S1/S2 purity, pickle boundary.
    """

    THREADS = "threads"
    PROCESSES = "processes"


@dataclass
class IsolationConfig:
    """Configuration for the isolation backend.

    Attributes:
        mode:          Isolation backend to use.
        concurrency:   Number of workers to spawn.
        tick_interval: Sleep gap (seconds) between handler invocations.
    """

    mode: IsolationMode = IsolationMode.THREADS
    concurrency: int = 1
    tick_interval: float = 0.05


# ---------------------------------------------------------------------------
# Worker implementations
# ---------------------------------------------------------------------------


class ThreadWorker(Thread):
    """A worker that runs inside a single process thread.

    Args:
        worker_id:     Numeric identifier.
        handler:       Stateless callable ``(worker_id) -> None``.
        stop_event:    Shared :class:`threading.Event` for shutdown.
        tick_interval: Sleep gap between handler invocations.
    """

    def __init__(
        self,
        worker_id: int,
        handler: Callable,
        stop_event: ThreadEvent,
        tick_interval: float = 0.05,
    ) -> None:
        super().__init__(name=f"worker-t{worker_id}", daemon=True)
        self.worker_id = worker_id
        self._handler = handler
        self._stop_event = stop_event
        self._tick_interval = tick_interval
        # S4.5.5: Track the job this worker is processing (None = idle).
        self.active_job_id: str | None = None

    def run(self) -> None:
        while not self._stop_event.is_set():
            self._handler(self.worker_id)
            time.sleep(self._tick_interval)


class ProcessWorker(Process):
    """A worker that runs in an isolated OS process.

    The *handler* **must** be pickleable (module-level function or a class
    that supports ``__reduce__``).  Lambda expressions will **not** work.

    Args:
        worker_id:     Numeric identifier.
        handler:       Pickleable, stateless callable ``(worker_id) -> None``.
        stop_event:    Shared :class:`multiprocessing.Event` for shutdown.
        tick_interval: Sleep gap between handler invocations.
    """

    def __init__(
        self,
        worker_id: int,
        handler: Callable,
        stop_event: ProcessEvent,
        tick_interval: float = 0.05,
    ) -> None:
        super().__init__(name=f"worker-p{worker_id}", daemon=True)
        self.worker_id = worker_id
        self._handler = handler
        self._stop_event = stop_event
        self._tick_interval = tick_interval
        # S4.5.5: Track the job this worker is processing (None = idle).
        self.active_job_id: str | None = None

    def run(self) -> None:
        while not self._stop_event.is_set():
            self._handler(self.worker_id)
            time.sleep(self._tick_interval)


# ---------------------------------------------------------------------------
# Pool base
# ---------------------------------------------------------------------------


class BaseWorkerPool(ABC):
    """Abstract lifecycle shared by thread and process pool implementations."""

    @abstractmethod
    def start(self) -> None:
        """Start all workers."""

    @abstractmethod
    def stop(self) -> None:
        """Signal all workers to shut down."""

    @abstractmethod
    def join(self) -> None:
        """Wait for all workers to finish."""

    @property
    @abstractmethod
    def worker_count(self) -> int:
        """Return the configured number of workers."""


# ---------------------------------------------------------------------------
# Thread pool
# ---------------------------------------------------------------------------


class ThreadWorkerPool(BaseWorkerPool):
    """A pool of :class:`ThreadWorker` instances.

    Args:
        config: Isolation config (mode is ignored — always THREADS).
        handler: Stateless callable ``(worker_id) -> None``.
        crash_recovery: Optional crash recovery logic (default: auto).
    """

    def __init__(
        self,
        config: IsolationConfig,
        handler: Callable,
        crash_recovery: WorkerCrashRecovery | None = None,
    ) -> None:
        self._concurrency = config.concurrency
        self._handler = handler
        self._tick_interval = config.tick_interval
        self._stop_event = ThreadEvent()
        self._workers: list[ThreadWorker] = [
            ThreadWorker(i, handler, self._stop_event, config.tick_interval)
            for i in range(config.concurrency)
        ]
        self._crash_recovery = crash_recovery or default_worker_crash_recovery()

    def start(self) -> None:
        for w in self._workers:
            w.start()

    def stop(self) -> None:
        self._stop_event.set()

    def join(self) -> None:
        for w in self._workers:
            w.join()

    @property
    def worker_count(self) -> int:
        return self._concurrency

    def handle_worker_exit(self, worker: ThreadWorker) -> WorkerPoolInstruction:
        """Evaluate a worker exit and produce restart/requeue instructions.

        Args:
            worker: The worker that exited.

        Returns:
            A :class:`WorkerPoolInstruction` with restart and requeue decisions.
        """
        import time as _time

        event = WorkerCrashEvent(
            worker_id=str(worker.worker_id),
            active_job_id=worker.active_job_id,
            timestamp=_time.time(),
        )
        return self._crash_recovery.evaluate(event)


# ---------------------------------------------------------------------------
# Process pool
# ---------------------------------------------------------------------------


class ProcessWorkerPool(BaseWorkerPool):
    """A pool of :class:`ProcessWorker` instances.

    The *handler* **must** be pickleable (module-level function).

    Args:
        config: Isolation config (mode is ignored — always PROCESSES).
        handler: Pickleable, stateless callable ``(worker_id) -> None``.
        crash_recovery: Optional crash recovery logic (default: auto).
    """

    def __init__(
        self,
        config: IsolationConfig,
        handler: Callable,
        crash_recovery: WorkerCrashRecovery | None = None,
    ) -> None:
        self._concurrency = config.concurrency
        self._handler = handler
        self._tick_interval = config.tick_interval
        self._stop_event = ProcessEvent()
        self._workers: list[ProcessWorker] = [
            ProcessWorker(i, handler, self._stop_event, config.tick_interval)
            for i in range(config.concurrency)
        ]
        self._crash_recovery = crash_recovery or default_worker_crash_recovery()

    def start(self) -> None:
        for w in self._workers:
            w.start()

    def stop(self) -> None:
        self._stop_event.set()

    def join(self) -> None:
        for w in self._workers:
            w.join()

    @property
    def worker_count(self) -> int:
        return self._concurrency

    def handle_worker_exit(self, worker: ProcessWorker) -> WorkerPoolInstruction:
        """Evaluate a worker exit and produce restart/requeue instructions.

        Args:
            worker: The worker that exited.

        Returns:
            A :class:`WorkerPoolInstruction` with restart and requeue decisions.
        """
        import time as _time

        event = WorkerCrashEvent(
            worker_id=str(worker.worker_id),
            active_job_id=worker.active_job_id,
            timestamp=_time.time(),
        )
        return self._crash_recovery.evaluate(event)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class WorkerPoolFactory:
    """Creates the appropriate :class:`BaseWorkerPool` for a given mode.

    Usage::

        pool = WorkerPoolFactory.create(config, handler)
        pool.start()
        # ...
        pool.stop()
        pool.join()
    """

    @staticmethod
    def create(config: IsolationConfig, handler: Callable) -> BaseWorkerPool:
        """Build a pool for *config.mode*.

        Args:
            config: :class:`IsolationConfig` with the desired backend.
            handler: Stateless (and pickleable for process mode) callable.

        Returns:
            A :class:`ThreadWorkerPool` or :class:`ProcessWorkerPool`.

        Raises:
            ValueError: If *config.mode* is not a recognised isolation mode.
        """
        if config.mode == IsolationMode.THREADS:
            return ThreadWorkerPool(config, handler)
        if config.mode == IsolationMode.PROCESSES:
            return ProcessWorkerPool(config, handler)
        raise ValueError(f"Unknown isolation mode: {config.mode}")

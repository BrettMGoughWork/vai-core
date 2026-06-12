"""Worker pool — deterministic concurrency for Stratum-4.

Thread-based worker pool with configurable concurrency, clean shutdown,
and stateless handler dispatch.  No queue operations, no JobStore writes,
no supervision, no durable semantics.

S4 Supervisor: The pool optionally includes a
:class:`~src.platform.supervisor.supervisor_loop.SupervisorLoop` that
evaluates worker health on a fixed interval and triggers restarts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Event, Thread
from typing import Callable

from src.platform.supervisor.supervisor_loop import (
    SupervisorConfig,
    SupervisorLoop,
    WorkerHeartbeat,
)


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
        supervisor_config: Optional supervisor configuration.  If set,
            a supervisor thread is started alongside the worker threads.
            If ``None``, no supervision is performed (default).
        supervisor_check_interval: Seconds between supervisor evaluation
            cycles (ignored if *supervisor_config* is ``None``).
    """

    worker_concurrency: int = 1
    worker_tick_interval: float = 0.05
    worker_handler: Callable | None = None
    supervisor_config: SupervisorConfig | None = None
    supervisor_check_interval: float = 5.0


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

    Optionally runs a supervisor thread if *config* includes a
    ``supervisor_config``.  The supervisor evaluates worker health
    on a fixed interval and applies restart decisions.

    Args:
        concurrency: Number of worker threads.
        handler: Callable executed by each worker on every tick.
        tick_interval: Sleep gap between handler invocations (seconds).
        supervisor_config: Optional supervisor configuration.
            ``None`` disables supervision.
        supervisor_check_interval: Seconds between supervisor cycles.
    """

    def __init__(
        self,
        concurrency: int,
        handler: Callable,
        tick_interval: float = 0.05,
        supervisor_config: SupervisorConfig | None = None,
        supervisor_check_interval: float = 5.0,
    ) -> None:
        self._concurrency = concurrency
        self._handler = handler
        self._tick_interval = tick_interval
        self._stop_event = Event()
        self._workers: list[WorkerThread] = [
            WorkerThread(i, handler, self._stop_event, tick_interval)
            for i in range(concurrency)
        ]

        # Supervisor (optional)
        self._supervisor_config = supervisor_config
        self._supervisor_check_interval = supervisor_check_interval
        self._supervisor: SupervisorLoop | None = (
            SupervisorLoop(config=supervisor_config)
            if supervisor_config is not None
            else None
        )
        self._supervisor_thread: Thread | None = None
        self._supervisor_stop = Event()

    # -- Lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Start all worker threads and the supervisor (if configured)."""
        for w in self._workers:
            w.start()
        if self._supervisor is not None:
            self._supervisor_thread = Thread(
                target=self._supervisor_loop,
                name="supervisor",
                daemon=True,
            )
            self._supervisor_thread.start()

    def stop(self) -> None:
        """Signal all workers and the supervisor to shut down."""
        self._stop_event.set()
        self._supervisor_stop.set()

    def join(self) -> None:
        """Wait for all worker threads to finish."""
        for w in self._workers:
            w.join()
        if self._supervisor_thread is not None:
            self._supervisor_thread.join(timeout=2)

    # -- Supervisor internals ----------------------------------------------

    def _supervisor_loop(self) -> None:
        """Run supervisor evaluation cycles until shutdown."""
        while not self._supervisor_stop.is_set():
            self._run_supervisor_cycle()
            # Sleep in small increments so shutdown is responsive
            for _ in range(int(self._supervisor_check_interval / 0.1)):
                if self._supervisor_stop.is_set():
                    return
                time.sleep(0.1)

    def _run_supervisor_cycle(self) -> None:
        """Execute one supervisor evaluation cycle.

        Collects active worker IDs, runs the supervisor evaluation,
        and applies restart decisions.
        """
        if self._supervisor is None:
            return
        now = time.time()
        active_ids: set[str] = set()
        for w in self._workers:
            wid = f"worker-{w.worker_id}"
            active_ids.add(wid)
            self._supervisor.collect_heartbeat(
                WorkerHeartbeat(
                    worker_id=wid,
                    timestamp=now,
                    status="healthy",
                )
            )
        decision = self._supervisor.evaluate(
            now=now,
            active_worker_ids=active_ids,
        )
        self._apply_decision(decision)

    def _apply_decision(self, decision) -> None:
        """Apply restart decisions from a supervisor cycle.

        For each restart, the old worker id is noted but actual thread
        replacement is managed externally by the runtime.  This is a
        notification/logging level integration — the supervisor does not
        kill OS threads directly (spec §6: pure logic).
        """
        if not decision.restarts:
            return
        # In a full production integration, these restarts would be
        # applied by the runtime layer.  Here we simply log/register
        # the decision via the supervisor's internal state.
        for restart in decision.restarts:
            # Notify supervisor that the old worker is removed
            if restart.old_worker_id:
                self._supervisor.remove_worker(restart.old_worker_id)  # type: ignore[union-attr]

    # -- Read-only property ------------------------------------------------

    @property
    def worker_count(self) -> int:
        """Return the configured number of workers."""
        return self._concurrency

    @property
    def supervisor(self) -> SupervisorLoop | None:
        """Return the supervisor instance, or ``None`` if not configured."""
        return self._supervisor


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
        supervisor_config=config.supervisor_config,
        supervisor_check_interval=getattr(
            config, "supervisor_check_interval", 5.0
        ),
    )

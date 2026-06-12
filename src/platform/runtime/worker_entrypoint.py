"""Worker entrypoint — Stratum-4 runtime integration stub.

Wires the :class:`~src.platform.runtime.worker_pool.BaseWorkerPool` into
the runtime lifecycle using the configurable isolation backend
(:class:`~src.platform.runtime.worker_pool.WorkerPoolFactory`).

Queue polling, job claiming, and execution will be added in S4.6–S4.7.
"""

from __future__ import annotations

from src.platform.queue.queue import Queue
from src.platform.runtime.config.runtime import RuntimeConcurrencyConfig
from src.platform.runtime.job_store.job_store import JobStore
from src.platform.runtime.worker_pool.isolation import (
    BaseWorkerPool,
    IsolationConfig,
    WorkerPoolFactory,
)
from src.platform.runtime.worker_pool.pool import (
    WorkerPoolConfig,
    create_worker_pool,
)


def _build_tick_handler(queue: Queue | None = None, job_store: JobStore | None = None):
    """Return a tick handler closure that captures dependencies.

    Args:
        queue:     Optional queue backend (for polling jobs).
        job_store: Optional persistence backend (for saving/loading jobs).

    The handler is a no-op stub until S4.6–S4.7 wires the full
    poll → claim → execute → ack cycle.
    """

    def handler(worker_id: int) -> None:
        pass

    return handler


def run_worker_pool(
    config: RuntimeConcurrencyConfig | WorkerPoolConfig | None = None,
    queue: Queue | None = None,
    job_store: JobStore | None = None,
) -> None:
    """Start the worker pool and block until shutdown.

    Accepts either the new :class:`RuntimeConcurrencyConfig` (with isolation
    backend selection) or the legacy :class:`WorkerPoolConfig` for backward
    compatibility.

    Args:
        config:    Isolation-aware or legacy config.  Falls back to defaults
                   when ``None``; the default handler is a no-op stub.
        queue:     Optional queue backend instance for the tick handler.
        job_store: Optional persistence backend for the tick handler.
    """
    if config is None:
        config = RuntimeConcurrencyConfig()

    tick_handler = _build_tick_handler(queue, job_store)

    # --- Legacy code path (WorkerPoolConfig) --------------------------------
    if isinstance(config, WorkerPoolConfig):
        if config.worker_handler is None:
            config.worker_handler = tick_handler
        pool = create_worker_pool(config)
        pool.start()
        try:
            pool.join()
        except KeyboardInterrupt:
            pool.stop()
            pool.join()
        return

    # --- New code path (RuntimeConcurrencyConfig with isolation) ------------
    iso_config = IsolationConfig(
        mode=config.isolation,
        concurrency=config.concurrency,
        tick_interval=config.tick_interval,
    )
    pool: BaseWorkerPool = WorkerPoolFactory.create(iso_config, tick_handler)
    pool.start()
    try:
        pool.join()
    except KeyboardInterrupt:
        pool.stop()
        pool.join()

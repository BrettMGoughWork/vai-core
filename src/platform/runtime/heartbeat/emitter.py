"""Heartbeat emitter — deterministic construction of HeartbeatEvent."""

from __future__ import annotations

import time
from typing import Callable

from src.platform.runtime.heartbeat.events import HeartbeatEvent


class HeartbeatEmitter:
    """Produces deterministic heartbeat events for a single worker.

    The emitter is pure logic — it constructs a well-typed
    :class:`HeartbeatEvent` from the provided inputs.  No IO, no
    persistence, no transport.

    Args:
        worker_id: Unique identifier for this worker.
        clock: A no-arg callable returning the current time in seconds
            (defaults to :func:`time.time`).  Inject a deterministic
            clock in tests.
    """

    def __init__(
        self,
        worker_id: str,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.worker_id = worker_id
        self._clock = clock if clock is not None else time.time

    def emit(
        self,
        active_job_id: str | None,
        cycles_completed: int,
        health: str,
    ) -> HeartbeatEvent:
        """Construct a heartbeat event for the current tick.

        Args:
            active_job_id: Job being processed, or ``None`` if idle.
            cycles_completed: Cumulative cycles completed by this worker.
            health: ``"ok"``, ``"idle"``, or ``"busy"``.

        Returns:
            A frozen :class:`HeartbeatEvent`.
        """
        return HeartbeatEvent(
            worker_id=self.worker_id,
            timestamp=self._clock(),
            active_job_id=active_job_id,
            cycles_completed=cycles_completed,
            health=health,
        )

"""Worker v1 — Stratum-4 runtime.

The simplest possible worker loop: pop a ``Job`` from the queue, call the S4→S1
adapter to prepare the request, execute against the cognitive strata (stubbed),
call the S1→S2 adapter to normalise the output, and update state via the
``ControlPlane``.  No concurrency, no retries, no lifecycle.
"""

from __future__ import annotations

import time
from typing import Any

from src.platform.adapter.adapter import s1_to_s2_adapter, s2_to_s1_adapter
from src.platform.observability.logging import log_job_started, log_job_finished
from src.platform.queue.queue import Queue
from src.platform.runtime.control_plane import ControlPlane
from src.platform.runtime.job import Job
from src.platform.transport.normalization import ChannelMessage


def _mock_execute(s1_request: dict[str, Any]) -> dict[str, Any]:
    """Temporary: stand-in for real S1 dispatch.

    Once S1 is wired, this function will be replaced by the actual S1
    execution path.  For now it echoes the input back as raw output.
    """
    return {"echo": s1_request.get("input", {})}


class Worker:
    """Processes one job per ``process_next()`` call.

    Args:
        queue:          The queue to poll for pending jobs.
        control_plane:  The ``ControlPlane`` that owns job state transitions.
    """

    def __init__(
        self,
        queue: Queue,
        control_plane: ControlPlane,
        timeout_seconds: int = 5,
    ) -> None:
        self._queue = queue
        self._cp = control_plane
        self.timeout_seconds = timeout_seconds

    def process_next(self) -> Job | None:
        """Pop the next job, execute it, and return the updated job.

        Steps:
            1. Pop a ``Job`` from the queue.
            2. If the queue is empty, return ``None``.
            3. ``ControlPlane.mark_running()`` — transition to ``RUNNING``.
            4. Record wall-clock start time.
            5. Call ``s2_to_s1_adapter()`` — transform ``ChannelMessage`` to S1 request.
            6. Execute against the cognitive strata (``_mock_execute``, replaced later).
            7. Call ``s1_to_s2_adapter()`` — transform raw output to S2 result.
            8. If elapsed wall time exceeds ``timeout_seconds``, mark FAILED with
               ``TimeoutError``.
            9. Otherwise ``ControlPlane.mark_succeeded()``.
            10. On exception: ``ControlPlane.mark_failed()``.
            11. Return the updated ``Job``.

        Returns:
            The updated ``Job``, or ``None`` if the queue was empty.
        """
        job = self._queue.pop()
        if job is None:
            return None

        self._cp.mark_running(job)
        log_job_started(job)

        try:
            start_time = time.monotonic()

            s1_request = s2_to_s1_adapter(job.payload)
            raw_output = _mock_execute(s1_request)
            result = s1_to_s2_adapter(raw_output)

            elapsed = time.monotonic() - start_time
            if elapsed > self.timeout_seconds:
                self._cp.mark_failed(
                    job,
                    {
                        "error_type": "TimeoutError",
                        "message": (
                            f"Job exceeded timeout of {self.timeout_seconds}s"
                        ),
                    },
                )
            else:
                self._cp.mark_succeeded(job, result)
        except Exception as e:
            self._cp.mark_failed(
                job,
                {"error_type": type(e).__name__, "message": str(e)},
            )

        log_job_finished(job)
        return job

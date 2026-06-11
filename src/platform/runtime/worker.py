"""Worker v1 — Stratum-4 runtime.

The simplest possible worker loop: pop a ``Job`` from the queue, call the
stub adapter, store the result, return the updated job.  No concurrency,
no retries, no lifecycle, no control plane.
"""

from __future__ import annotations

from typing import Any

from src.platform.observability.logging import log_job_started, log_job_finished
from src.platform.queue.queue import Queue
from src.platform.runtime.job import Job
from src.platform.transport.normalization import ChannelMessage


def execute_job_payload(payload: ChannelMessage) -> dict[str, Any]:
    """Stub S4→S1/S2/S3 adapter.

    Placeholder that echoes the input back.  Replace with the real
    cross-stratum dispatch once S1/S2/S3 wiring is defined.
    """
    return {"status": "ok", "echo": payload.input}


class Worker:
    """Processes one job per ``process_next()`` call.

    Args:
        queue: The queue to poll for pending jobs.
    """

    def __init__(self, queue: Queue) -> None:
        self._queue = queue

    def process_next(self) -> Job | None:
        """Pop the next job, execute it, and return the updated job.

        Steps:
            1. Pop a ``Job`` from the queue.
            2. If the queue is empty, return ``None``.
            3. Call ``execute_job_payload(job.payload)``.
            4. Store the result in ``job.result``.
            5. Return the updated ``Job``.

        Returns:
            The updated ``Job``, or ``None`` if the queue was empty.
        """
        job = self._queue.pop()
        if job is None:
            return None

        log_job_started(job)
        result = execute_job_payload(job.payload)
        job.result = result
        log_job_finished(job)
        return job

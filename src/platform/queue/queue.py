"""Queue v1 — Stratum-4 runtime.

A simple, stable FIFO queue that accepts ``Job`` instances.
The interface is designed to survive replacement of the in-memory
backing with Redis/SQS/etc.
"""

from __future__ import annotations

from collections import deque

from src.platform.runtime.job import Job


class Queue:
    """Interface for a FIFO job queue.

    Implementations must satisfy FIFO semantics.
    """

    def push(self, job: Job) -> str:
        """Enqueue *job* and return its ``job_id``."""
        raise NotImplementedError

    def pop(self) -> Job | None:
        """Dequeue the oldest job, or ``None`` if empty."""
        raise NotImplementedError

    def __len__(self) -> int:
        """Return the number of jobs currently in the queue."""
        raise NotImplementedError


class InMemoryQueue(Queue):
    """In-memory FIFO queue backed by ``collections.deque``.

    No persistence, no concurrency, no async.  Intended as a
    development / test stand-in for a production queue.
    """

    def __init__(self) -> None:
        self._items: deque[Job] = deque()

    def push(self, job: Job) -> str:
        """Append *job* and return its ``job_id``."""
        self._items.append(job)
        return job.job_id

    def pop(self) -> Job | None:
        """Remove and return the oldest job, or ``None`` if empty."""
        try:
            return self._items.popleft()
        except IndexError:
            return None

    def __len__(self) -> int:
        """Return the number of jobs in the queue."""
        return len(self._items)

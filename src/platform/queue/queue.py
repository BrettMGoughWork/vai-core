"""Queue v1 — Stratum-4 runtime.

A simple, stable FIFO queue that accepts ``Job`` instances.
The interface is designed to survive replacement of the in-memory
backing with Redis/SQS/etc.
"""

from __future__ import annotations

from collections import deque

from src.platform.runtime.job import Job


class Queue:
    """Abstract interface for a FIFO job queue with lease semantics.

    Implementations must satisfy FIFO semantics.
    """

    def push(self, job: Job) -> str:
        """Enqueue *job* and return its ``job_id``."""
        raise NotImplementedError

    def pop(self) -> Job | None:
        """Dequeue the oldest job, or ``None`` if empty.

        The returned job is considered *leased* — it is removed from the
        main queue but must be explicitly acknowledged, requeued, or
        nacked to release the lease.
        """
        raise NotImplementedError

    def acknowledge(self, job_id: str) -> None:
        """Mark *job_id* as successfully processed and release its lease."""
        raise NotImplementedError

    def requeue(self, job_id: str) -> None:
        """Return *job_id* to the front of the queue for retry."""
        raise NotImplementedError

    def nack(self, job_id: str) -> None:
        """Mark *job_id* as failed (dead-letter)."""
        raise NotImplementedError

    def __len__(self) -> int:
        """Return the number of jobs currently in the queue."""
        raise NotImplementedError


class InMemoryQueue(Queue):
    """In-memory FIFO queue backed by ``collections.deque``.

    Simulates the Redis RPOPLPUSH lease pattern using an in-flight dict:
    popped jobs are tracked until acknowledged, requeued, or nacked.

    No persistence, no concurrency, no async.  Intended as a
    development / test stand-in for a production queue.
    """

    def __init__(self) -> None:
        self._items: deque[Job] = deque()
        self._in_flight: dict[str, Job] = {}

    def push(self, job: Job) -> str:
        """Append *job* and return its ``job_id``."""
        self._items.append(job)
        return job.job_id

    def pop(self) -> Job | None:
        """Remove and return the oldest job, or ``None`` if empty.

        The returned job is tracked as in-flight until acknowledged,
        requeued, or nacked.
        """
        try:
            job = self._items.popleft()
            self._in_flight[job.job_id] = job
            return job
        except IndexError:
            return None

    def acknowledge(self, job_id: str) -> None:
        """Release the lease on *job_id* (remove from in-flight)."""
        self._in_flight.pop(job_id, None)

    def requeue(self, job_id: str) -> None:
        """Return *job_id* to the front of the queue."""
        job = self._in_flight.pop(job_id, None)
        if job is not None:
            self._items.appendleft(job)

    def nack(self, job_id: str) -> None:
        """Remove *job_id* from in-flight (discard)."""
        self._in_flight.pop(job_id, None)

    def __len__(self) -> int:
        """Return the number of jobs in the queue."""
        return len(self._items)

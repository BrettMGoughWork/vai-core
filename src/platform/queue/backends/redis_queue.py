"""Redis List queue backend — Stratum-4 runtime.

Uses Redis ``RPOPLPUSH`` for atomic lease semantics: ``pop()`` atomically
moves the serialised ``Job`` from the main queue to a processing list.
``acknowledge()`` removes the job from processing; ``requeue()`` moves it
back to the main queue.

Requires ``redis-py`` (``pip install redis``).
"""

from __future__ import annotations

import json

from src.platform.queue.queue import Queue
from src.platform.runtime.job import Job

try:
    import redis as _redis

    HAS_REDIS = True
except ImportError:  # pragma: no cover
    HAS_REDIS = False


def _serialise(job: Job) -> str:
    """Return a JSON string for *job*."""
    return job.model_dump_json()


def _deserialise(data: str) -> Job:
    """Reconstruct a ``Job`` from its JSON string."""
    return Job.model_validate_json(data)


class RedisListQueue(Queue):
    """FIFO queue backed by a Redis List with RPOPLPUSH lease semantics.

    Args:
        redis_url:       Redis connection URL
                         (e.g. ``redis://localhost:6379/0``).
        queue_key:       Redis key for the main job queue (list).
        processing_key:  Redis key for the in-flight / processing list.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        queue_key: str = "vai:queue",
        processing_key: str = "vai:processing",
    ) -> None:
        if not HAS_REDIS:
            raise ImportError(
                "redis-py is required for RedisListQueue. "
                "Install with: pip install redis"
            )
        self._client = _redis.from_url(redis_url)
        self._queue_key = queue_key
        self._processing_key = processing_key

    def push(self, job: Job) -> str:
        """Enqueue *job* by LPUSH onto the main queue list."""
        self._client.lpush(self._queue_key, _serialise(job))
        return job.job_id

    def pop(self) -> Job | None:
        """Atomically RPOPLPUSH from main queue to processing list.

        Returns the deserialised ``Job``, or ``None`` if the queue is
        empty.
        """
        data = self._client.rpoplpush(self._queue_key, self._processing_key)
        if data is None:
            return None
        return _deserialise(data)

    def acknowledge(self, job_id: str) -> None:
        """Remove *job_id* from the processing list."""
        self._remove_from_list(self._processing_key, job_id)

    def requeue(self, job_id: str) -> None:
        """Move *job_id* from processing back to the main queue."""
        for item in self._client.lrange(self._processing_key, 0, -1):
            try:
                job_data = json.loads(item)
                if job_data.get("job_id") == job_id:
                    self._client.lrem(self._processing_key, 1, item)
                    self._client.lpush(self._queue_key, item)
                    return
            except (json.JSONDecodeError, KeyError):
                continue

    def nack(self, job_id: str) -> None:
        """Mark *job_id* failed — remove from processing (no dead-letter)."""
        self._remove_from_list(self._processing_key, job_id)

    def __len__(self) -> int:
        """Return the number of jobs in the main queue."""
        return self._client.llen(self._queue_key)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _remove_from_list(self, key: str, job_id: str) -> None:
        """Scan the Redis *key* for a serialised job with *job_id* and remove it."""
        for item in self._client.lrange(key, 0, -1):
            try:
                job_data = json.loads(item)
                if job_data.get("job_id") == job_id:
                    self._client.lrem(key, 1, item)
                    return
            except (json.JSONDecodeError, KeyError):
                continue

"""Queue factory — Stratum-4 runtime.

Provides ``QueueConfig`` for configuring the queue backend and
``create_queue()`` to materialise the appropriate implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.platform.queue.queue import InMemoryQueue, Queue


@dataclass
class QueueConfig:
    """Configuration for the Stratum-4 queue backend.

    Attributes:
        backend:          Queue implementation — ``"memory"`` or ``"redis"``.
        redis_url:        Redis connection URL (only used when
                          ``backend="redis"``).
        redis_queue_key:  Redis key for the main job queue list.
        redis_processing_key: Redis key for the in-flight / processing list.
    """

    backend: str = "memory"
    redis_url: str = "redis://localhost:6379/0"
    redis_queue_key: str = "vai:queue"
    redis_processing_key: str = "vai:processing"


def create_queue(config: QueueConfig | None = None) -> Queue:
    """Build and return a ``Queue`` implementation based on *config*.

    Args:
        config:  Queue configuration.  Falls back to
                 ``QueueConfig(backend="memory")`` when ``None``.

    Returns:
        An ``InMemoryQueue`` or ``RedisListQueue`` instance.

    Raises:
        ValueError:  If ``config.backend`` is not a recognised value.
    """
    if config is None:
        config = QueueConfig()

    if config.backend == "memory":
        return InMemoryQueue()
    if config.backend == "redis":
        from src.platform.queue.backends.redis_queue import RedisListQueue

        return RedisListQueue(
            redis_url=config.redis_url,
            queue_key=config.redis_queue_key,
            processing_key=config.redis_processing_key,
        )

    msg = f"Unknown queue backend: {config.backend!r} (expected 'memory' or 'redis')"
    raise ValueError(msg)

"""Queue package for Stratum-4 runtime.

Provides the abstract ``Queue`` interface, an ``InMemoryQueue`` for
dev/testing, a ``RedisListQueue`` for production, and a factory to
materialise the configured backend.
"""

from src.platform.queue.factory import QueueConfig, create_queue
from src.platform.queue.queue import InMemoryQueue, Queue

__all__ = [
    "InMemoryQueue",
    "Queue",
    "QueueConfig",
    "create_queue",
]

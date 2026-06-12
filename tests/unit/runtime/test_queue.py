"""Tests for S4.5.0 Queue Backend Abstraction.

Covers:
- InMemoryQueue lease semantics (acknowledge/requeue/nack)
- QueueConfig + create_queue() factory
- Factory error paths
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.platform.queue.factory import QueueConfig, create_queue
from src.platform.queue.queue import InMemoryQueue, Queue
from src.platform.runtime.job import Job
from src.platform.runtime.job_state import JobState
from src.platform.transport.normalization import ChannelMessage


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_job() -> Job:
    return Job(
        job_id=str(uuid4()),
        created_at=datetime.now(timezone.utc),
        state=JobState.PENDING,
        payload=ChannelMessage(input={"text": "hello"}),
    )


# ------------------------------------------------------------------
# InMemoryQueue lease semantics
# ------------------------------------------------------------------


class TestInMemoryQueueBasic:
    """push / pop / __len__ basic contract."""

    def test_push_and_pop_fifo(self):
        q: Queue = InMemoryQueue()
        j1, j2 = _make_job(), _make_job()
        q.push(j1)
        q.push(j2)
        assert q.pop() is j1
        assert q.pop() is j2

    def test_pop_returns_none_when_empty(self):
        q: Queue = InMemoryQueue()
        assert q.pop() is None

    def test_len(self):
        q: Queue = InMemoryQueue()
        assert len(q) == 0
        q.push(_make_job())
        assert len(q) == 1


class TestInMemoryQueueLease:
    """acknowledge / requeue / nack lifecycle."""

    def test_acknowledge_releases_lease(self):
        q: Queue = InMemoryQueue()
        job = _make_job()
        q.push(job)
        popped = q.pop()
        assert popped is not None

        q.acknowledge(popped.job_id)
        # job should no longer be in-flight; queue is empty
        assert q.pop() is None

    def test_requeue_returns_job_to_front(self):
        q: Queue = InMemoryQueue()
        j1, j2 = _make_job(), _make_job()
        q.push(j1)
        q.push(j2)
        popped = q.pop()
        assert popped is j1

        q.requeue(popped.job_id)
        # j1 should be back at front
        assert q.pop() is j1

    def test_nack_discards_job(self):
        q: Queue = InMemoryQueue()
        job = _make_job()
        q.push(job)
        popped = q.pop()
        assert popped is not None

        q.nack(popped.job_id)
        # job is gone — queue is empty
        assert q.pop() is None

    def test_acknowledge_unknown_id_is_noop(self):
        q: Queue = InMemoryQueue()
        q.acknowledge("nope")  # should not raise

    def test_requeue_unknown_id_is_noop(self):
        q: Queue = InMemoryQueue()
        q.requeue("nope")  # should not raise

    def test_full_lease_lifecycle(self):
        q: Queue = InMemoryQueue()
        job = _make_job()
        q.push(job)
        assert len(q) == 1

        popped = q.pop()
        assert popped is not None
        assert popped.job_id == job.job_id
        assert len(q) == 0  # removed from main queue

        # released from in-flight via ack
        q.acknowledge(job.job_id)
        assert q.pop() is None  # still empty


# ------------------------------------------------------------------
# Factory
# ------------------------------------------------------------------


class TestCreateQueue:
    """QueueConfig + create_queue() factory."""

    def test_default_config_returns_in_memory(self):
        q = create_queue()
        assert isinstance(q, InMemoryQueue)

    def test_memory_backend(self):
        config = QueueConfig(backend="memory")
        q = create_queue(config)
        assert isinstance(q, InMemoryQueue)

    def test_redis_backend_raises_without_lib(self):
        config = QueueConfig(backend="redis")
        with pytest.raises(ImportError, match="redis-py"):
            create_queue(config)

    def test_unknown_backend_raises(self):
        config = QueueConfig(backend="kafka")
        with pytest.raises(ValueError, match="Unknown queue backend"):
            create_queue(config)


class TestQueueConfigDefaults:
    """QueueConfig field defaults."""

    def test_backend_defaults_to_memory(self):
        config = QueueConfig()
        assert config.backend == "memory"

    def test_redis_url_default(self):
        config = QueueConfig()
        assert config.redis_url == "redis://localhost:6379/0"

    def test_queue_key_default(self):
        config = QueueConfig()
        assert config.redis_queue_key == "vai:queue"

    def test_processing_key_default(self):
        config = QueueConfig()
        assert config.redis_processing_key == "vai:processing"

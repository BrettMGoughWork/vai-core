"""Tests for S4.5.6 Persistence Backend Abstraction.

Covers:
- InMemoryJobStore CRUD
- SqliteJobStore CRUD
- JobStoreConfig + create_job_store() factory
- Factory error paths
- Backward-compatible singleton
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.platform.runtime.job import Job
from src.platform.runtime.job_state import JobState
from src.platform.runtime.job_store.factory import JobStoreConfig, create_job_store
from src.platform.runtime.job_store.job_store import InMemoryJobStore, JobStore
from src.platform.transport.normalization import ChannelMessage


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_job(**overrides) -> Job:
    defaults = dict(
        job_id=str(uuid4()),
        created_at=datetime.now(timezone.utc),
        state=JobState.PENDING,
        payload=ChannelMessage(input={"content": "test payload"}, metadata={"source": "test"}),
    )
    defaults.update(overrides)
    return Job(**defaults)


# ------------------------------------------------------------------
# Shared CRUD tests (parameterised over all backends)
# ------------------------------------------------------------------

BACKEND_FIXTURES = [
    pytest.param("inmemory", id="inmemory"),
    pytest.param("sqlite_file", id="sqlite"),
    pytest.param("sqlite_memory", id="sqlite-memory"),
]


@pytest.fixture
def store(request):
    """Yield a fresh JobStore instance for each backend variant."""
    label = request.param
    if label == "inmemory":
        yield InMemoryJobStore()
    elif label == "sqlite_file":
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        from src.platform.runtime.job_store.backends.sqlite_job_store import (
            SqliteJobStore,
        )
        s = SqliteJobStore(db_path=db_path)
        yield s
        s.close()
        os.unlink(db_path)
    elif label == "sqlite_memory":
        from src.platform.runtime.job_store.backends.sqlite_job_store import (
            SqliteJobStore,
        )
        s = SqliteJobStore(db_path=":memory:")
        yield s
        s.close()
    else:
        raise ValueError(f"Unknown backend fixture: {label}")


class TestJobStoreCRUD:
    """Save / get / list / delete / length across all backends."""

    @pytest.mark.parametrize("store", BACKEND_FIXTURES, indirect=True)
    def test_save_and_get(self, store: JobStore) -> None:
        job = _make_job()
        store.save(job)
        retrieved = store.get(job.job_id)
        assert retrieved is not None
        assert retrieved.job_id == job.job_id
        assert retrieved.payload.metadata["source"] == "test"

    @pytest.mark.parametrize("store", BACKEND_FIXTURES, indirect=True)
    def test_get_missing_returns_none(self, store: JobStore) -> None:
        assert store.get("nonexistent") is None

    @pytest.mark.parametrize("store", BACKEND_FIXTURES, indirect=True)
    def test_save_overwrite(self, store: JobStore) -> None:
        job = _make_job(state=JobState.PENDING)
        store.save(job)
        job.state = JobState.RUNNING
        store.save(job)
        retrieved = store.get(job.job_id)
        assert retrieved is not None
        assert retrieved.state == JobState.RUNNING

    @pytest.mark.parametrize("store", BACKEND_FIXTURES, indirect=True)
    def test_list_empty(self, store: JobStore) -> None:
        assert store.list() == []

    @pytest.mark.parametrize("store", BACKEND_FIXTURES, indirect=True)
    def test_list_returns_all_jobs(self, store: JobStore) -> None:
        jobs = [_make_job() for _ in range(3)]
        for j in jobs:
            store.save(j)
        meta = store.list()
        assert len(meta) == 3
        ids = {m["job_id"] for m in meta}
        assert ids == {j.job_id for j in jobs}

    @pytest.mark.parametrize("store", BACKEND_FIXTURES, indirect=True)
    def test_delete_removes_job(self, store: JobStore) -> None:
        job = _make_job()
        store.save(job)
        store.delete(job.job_id)
        assert store.get(job.job_id) is None

    @pytest.mark.parametrize("store", BACKEND_FIXTURES, indirect=True)
    def test_delete_missing_is_noop(self, store: JobStore) -> None:
        store.delete("nonexistent")  # should not raise

    @pytest.mark.parametrize("store", BACKEND_FIXTURES, indirect=True)
    def test_len(self, store: JobStore) -> None:
        assert len(store) == 0
        store.save(_make_job())
        assert len(store) == 1
        store.save(_make_job())
        assert len(store) == 2

    @pytest.mark.parametrize("store", BACKEND_FIXTURES, indirect=True)
    def test_round_trip_preserves_fields(self, store: JobStore) -> None:
        """All Job fields survive a save → get round-trip."""
        from src.platform.runtime.execution_context import ExecutionContext

        ctx = ExecutionContext(history=[], pending_tools=[], context={}, cognitive_scope={})
        job = _make_job(
            result={"answer": 42},
            trace=[{"event": "created", "ts": "now"}],
            execution_context=ctx,
            resume_token="tok-1",
            failure_count=2,
            consecutive_failures=1,
            panic_count=0,
            crash_count=0,
        )
        store.save(job)
        retrieved = store.get(job.job_id)
        assert retrieved is not None
        assert retrieved.result == {"answer": 42}
        assert retrieved.trace == [{"event": "created", "ts": "now"}]
        assert retrieved.execution_context is not None
        assert retrieved.resume_token == "tok-1"
        assert retrieved.failure_count == 2
        assert retrieved.consecutive_failures == 1


# ------------------------------------------------------------------
# Factory tests
# ------------------------------------------------------------------


class TestJobStoreFactory:
    def test_create_inmemory_default(self) -> None:
        store = create_job_store()
        assert isinstance(store, InMemoryJobStore)

    def test_create_inmemory_explicit(self) -> None:
        config = JobStoreConfig(backend="memory")
        store = create_job_store(config)
        assert isinstance(store, InMemoryJobStore)

    def test_create_sqlite(self) -> None:
        config = JobStoreConfig(backend="sqlite", sqlite_path=":memory:")
        store = create_job_store(config)
        from src.platform.runtime.job_store.backends.sqlite_job_store import (
            SqliteJobStore,
        )
        assert isinstance(store, SqliteJobStore)
        store.save(_make_job())
        assert len(store) == 1
        store.close()

    def test_factory_none_config(self) -> None:
        store = create_job_store(None)
        assert isinstance(store, InMemoryJobStore)

    def test_invalid_backend_raises(self) -> None:
        config = JobStoreConfig(backend="mongodb")
        with pytest.raises(ValueError, match="Unknown job store backend"):
            create_job_store(config)


# ------------------------------------------------------------------
# Backward-compatible singleton
# ------------------------------------------------------------------


class TestJobStoreSingleton:
    def test_backward_compat_import(self) -> None:
        from src.platform.runtime.job_store import job_store as singleton

        assert isinstance(singleton, InMemoryJobStore)
        job = _make_job()
        singleton.save(job)
        assert singleton.get(job.job_id) is not None
        # Restore clean state
        singleton.delete(job.job_id)

    def test_two_imports_are_same_object(self) -> None:
        from src.platform.runtime.job_store import job_store as s1
        from src.platform.runtime.job_store.job_store import _default_store as s2
        assert s1 is s2

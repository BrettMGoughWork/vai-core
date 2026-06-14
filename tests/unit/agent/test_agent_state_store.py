"""
Phase 5.6 — AgentStateStore Unit Tests
=======================================

Tests for all three store backends:
- MemoryAgentStateStore
- FileAgentStateStore
- SQLiteAgentStateStore

Each backend is tested against the same contract:
- save → load roundtrip
- overwrite semantics
- missing agent returns None
- list_agent_ids
- error guards (empty agent_id)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest

from src.agent.contracts import (
    ACTION_REQUEST_S4_JOB_INTENT,
    ActionIntent,
)
from src.agent.adapters.memory_agent_state_store import MemoryAgentStateStore
from src.agent.adapters.file_agent_state_store import FileAgentStateStore
from src.agent.adapters.sqlite_agent_state_store import SQLiteAgentStateStore
from src.agent.interfaces.agent_state import AgentState, LifecycleState
from src.agent.interfaces.agent_state_store import StoreError


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def tmp_dir() -> Generator[Path, None, None]:
    """Yield a temporary directory that is cleaned up after the test."""
    path = Path(tempfile.mkdtemp())
    try:
        yield path
    finally:
        for child in path.glob("*"):
            try:
                os.remove(child)
            except OSError:
                pass
        try:
            path.rmdir()
        except OSError:
            pass


@pytest.fixture
def agent_state() -> AgentState:
    """A minimal valid AgentState for store roundtrip tests."""
    return AgentState(
        agent_id="test-agent",
        lifecycle_state=LifecycleState.CREATED,
        timestamps={"created_at": "2024-01-01T00:00:00+00:00"},
        correlation_id="corr-123",
        trace_id="trace-456",
    )


@pytest.fixture
def populated_agent_state() -> AgentState:
    """A richer AgentState representing a mid-lifecycle agent."""
    return AgentState(
        agent_id="active-agent",
        lifecycle_state=LifecycleState.WAITING,
        pending_intents=[
            ActionIntent(
                type=ACTION_REQUEST_S4_JOB_INTENT,
                payload={"job_type": "test", "params": {"x": 1}},
            ),
        ],
        timestamps={
            "created_at": "2024-01-01T00:00:00+00:00",
            "activated_at": "2024-01-01T00:00:01+00:00",
            "last_run_at": "2024-01-01T00:00:02+00:00",
        },
        correlation_id="corr-active",
        trace_id="trace-active",
        version=3,
        supervisor_metadata={"total_iterations": 2},
    )


# ══════════════════════════════════════════════════════════════════════════════
# MemoryAgentStateStore
# ══════════════════════════════════════════════════════════════════════════════


class TestMemoryAgentStateStore:
    """Tests for the in-memory store backend."""

    def test_save_and_load_roundtrip(self, agent_state: AgentState) -> None:
        store = MemoryAgentStateStore()
        store.save("test-agent", agent_state)
        loaded = store.load("test-agent")
        assert loaded is not None
        assert loaded.agent_id == "test-agent"
        assert loaded.lifecycle_state == LifecycleState.CREATED
        assert loaded.version == agent_state.version + 0  # save increments via with_, not here

    def test_overwrite_updates_state(self, agent_state: AgentState) -> None:
        store = MemoryAgentStateStore()
        store.save("test-agent", agent_state)
        updated = agent_state.with_(lifecycle_state=LifecycleState.ACTIVATED)
        store.save("test-agent", updated)
        loaded = store.load("test-agent")
        assert loaded is not None
        assert loaded.lifecycle_state == LifecycleState.ACTIVATED
        assert loaded.version == agent_state.version + 1  # with_ increments

    def test_load_missing_returns_none(self) -> None:
        store = MemoryAgentStateStore()
        assert store.load("nonexistent") is None

    def test_list_agent_ids_empty(self) -> None:
        store = MemoryAgentStateStore()
        assert store.list_agent_ids() == []

    def test_list_agent_ids_after_save(self, agent_state: AgentState) -> None:
        store = MemoryAgentStateStore()
        store.save("agent-a", agent_state)
        store.save("agent-b", agent_state)
        ids = store.list_agent_ids()
        assert sorted(ids) == ["agent-a", "agent-b"]

    def test_save_empty_agent_id_raises(self, agent_state: AgentState) -> None:
        store = MemoryAgentStateStore()
        with pytest.raises(StoreError, match="agent_id must be non-empty"):
            store.save("", agent_state)

    def test_load_empty_agent_id_returns_none(self) -> None:
        store = MemoryAgentStateStore()
        assert store.load("") is None

    def test_immutability_on_read(self, agent_state: AgentState) -> None:
        """Verify that loading returns a deep copy."""
        store = MemoryAgentStateStore()
        store.save("test-agent", agent_state)
        loaded = store.load("test-agent")
        assert loaded is not None

        # Mutating the loaded state should not affect the store
        import dataclasses
        mutated = dataclasses.replace(loaded, lifecycle_state=LifecycleState.COMPLETED)
        reloaded = store.load("test-agent")
        assert reloaded is not None
        assert reloaded.lifecycle_state == LifecycleState.CREATED
        assert reloaded.version == 1

    def test_rich_state_roundtrip(self, populated_agent_state: AgentState) -> None:
        """Verify that a complex AgentState with nested types survives save/load."""
        store = MemoryAgentStateStore()
        store.save("active-agent", populated_agent_state)
        loaded = store.load("active-agent")
        assert loaded is not None
        assert loaded.agent_id == "active-agent"
        assert loaded.lifecycle_state == LifecycleState.WAITING
        assert loaded.pending_intents is not None
        assert len(loaded.pending_intents) == 1
        assert loaded.pending_intents[0].type == ACTION_REQUEST_S4_JOB_INTENT
        assert loaded.version == 3
        assert loaded.supervisor_metadata.get("total_iterations") == 2


# ══════════════════════════════════════════════════════════════════════════════
# FileAgentStateStore
# ══════════════════════════════════════════════════════════════════════════════


class TestFileAgentStateStore:
    """Tests for the file-backed store backend."""

    # ── Happy path ───────────────────────────────────────────────────────

    def test_save_and_load_roundtrip(self, tmp_dir: Path, agent_state: AgentState) -> None:
        store = FileAgentStateStore(tmp_dir)
        store.save("test-agent", agent_state)
        loaded = store.load("test-agent")
        assert loaded is not None
        assert loaded.agent_id == "test-agent"
        assert loaded.lifecycle_state == LifecycleState.CREATED

    def test_overwrite_updates_state(self, tmp_dir: Path, agent_state: AgentState) -> None:
        store = FileAgentStateStore(tmp_dir)
        store.save("test-agent", agent_state)
        updated = agent_state.with_(lifecycle_state=LifecycleState.ACTIVATED)
        store.save("test-agent", updated)
        loaded = store.load("test-agent")
        assert loaded is not None
        assert loaded.lifecycle_state == LifecycleState.ACTIVATED

    def test_load_missing_returns_none(self, tmp_dir: Path) -> None:
        store = FileAgentStateStore(tmp_dir)
        assert store.load("nonexistent") is None

    def test_list_agent_ids(self, tmp_dir: Path, agent_state: AgentState) -> None:
        store = FileAgentStateStore(tmp_dir)
        store.save("agent-a", agent_state)
        store.save("agent-b", agent_state)
        ids = store.list_agent_ids()
        assert sorted(ids) == ["agent-a", "agent-b"]

    def test_rich_state_roundtrip(self, tmp_dir: Path, populated_agent_state: AgentState) -> None:
        """Verify that nested types (ActionIntent, LifecycleEvent) survive file serialisation."""
        store = FileAgentStateStore(tmp_dir)
        store.save("active-agent", populated_agent_state)
        loaded = store.load("active-agent")
        assert loaded is not None
        assert loaded.agent_id == "active-agent"
        assert loaded.lifecycle_state == LifecycleState.WAITING
        assert loaded.pending_intents is not None
        assert len(loaded.pending_intents) == 1
        assert loaded.pending_intents[0].type == ACTION_REQUEST_S4_JOB_INTENT

    # ── Edge cases ───────────────────────────────────────────────────────

    def test_storage_dir_created_automatically(self, tmp_dir: Path, agent_state: AgentState) -> None:
        """The store should create the storage directory if it doesn't exist."""
        nested = tmp_dir / "deep" / "nested" / "store"
        store = FileAgentStateStore(nested)
        store.save("test-agent", agent_state)
        assert nested.exists()
        assert nested.is_dir()
        loaded = store.load("test-agent")
        assert loaded is not None

    def test_empty_agent_id_raises_on_save(self, tmp_dir: Path, agent_state: AgentState) -> None:
        store = FileAgentStateStore(tmp_dir)
        with pytest.raises(StoreError, match="agent_id must be non-empty"):
            store.save("", agent_state)

    def test_empty_agent_id_raises_on_load(self, tmp_dir: Path) -> None:
        store = FileAgentStateStore(tmp_dir)
        with pytest.raises(StoreError, match="agent_id must be non-empty"):
            store.load("")

    def test_path_separator_in_agent_id_raises(
        self, tmp_dir: Path, agent_state: AgentState
    ) -> None:
        store = FileAgentStateStore(tmp_dir)
        with pytest.raises(StoreError, match="invalid agent_id"):
            store.save("foo/bar", agent_state)
        with pytest.raises(StoreError, match="invalid agent_id"):
            store.save("foo\\bar", agent_state)
        with pytest.raises(StoreError, match="invalid agent_id"):
            store.save("..", agent_state)

    def test_corrupted_file_raises(self, tmp_dir: Path) -> None:
        """A manually corrupted JSON file should raise StoreError on load."""
        bad_file = tmp_dir / "corrupt.json"
        bad_file.write_text("{bad json", encoding="utf-8")
        store = FileAgentStateStore(tmp_dir)
        with pytest.raises(StoreError, match="failed to load"):
            store.load("corrupt")


# ══════════════════════════════════════════════════════════════════════════════
# SQLiteAgentStateStore
# ══════════════════════════════════════════════════════════════════════════════


class TestSQLiteAgentStateStore:
    """Tests for the SQLite-backed store backend."""

    # ── Happy path ───────────────────────────────────────────────────────

    def test_save_and_load_roundtrip(self, tmp_dir: Path, agent_state: AgentState) -> None:
        db_path = tmp_dir / "test.db"
        store = SQLiteAgentStateStore(db_path)
        store.save("test-agent", agent_state)
        loaded = store.load("test-agent")
        assert loaded is not None
        assert loaded.agent_id == "test-agent"
        assert loaded.lifecycle_state == LifecycleState.CREATED

    def test_overwrite_updates_state(self, tmp_dir: Path, agent_state: AgentState) -> None:
        db_path = tmp_dir / "test.db"
        store = SQLiteAgentStateStore(db_path)
        store.save("test-agent", agent_state)
        updated = agent_state.with_(lifecycle_state=LifecycleState.ACTIVATED)
        store.save("test-agent", updated)
        loaded = store.load("test-agent")
        assert loaded is not None
        assert loaded.lifecycle_state == LifecycleState.ACTIVATED
        # version incremented by with_()
        assert loaded.version == agent_state.version + 1

    def test_load_missing_returns_none(self, tmp_dir: Path) -> None:
        db_path = tmp_dir / "test.db"
        store = SQLiteAgentStateStore(db_path)
        assert store.load("nonexistent") is None

    def test_list_agent_ids(self, tmp_dir: Path, agent_state: AgentState) -> None:
        db_path = tmp_dir / "test.db"
        store = SQLiteAgentStateStore(db_path)
        store.save("agent-a", agent_state)
        store.save("agent-b", agent_state)
        ids = store.list_agent_ids()
        assert sorted(ids) == ["agent-a", "agent-b"]

    def test_rich_state_roundtrip(self, tmp_dir: Path, populated_agent_state: AgentState) -> None:
        """Verify that nested types survive SQLite serialisation."""
        db_path = tmp_dir / "test.db"
        store = SQLiteAgentStateStore(db_path)
        store.save("active-agent", populated_agent_state)
        loaded = store.load("active-agent")
        assert loaded is not None
        assert loaded.agent_id == "active-agent"
        assert loaded.lifecycle_state == LifecycleState.WAITING
        assert loaded.pending_intents is not None
        assert len(loaded.pending_intents) == 1
        assert loaded.pending_intents[0].type == ACTION_REQUEST_S4_JOB_INTENT
        assert loaded.version == 3

    # ── Edge cases ───────────────────────────────────────────────────────

    def test_empty_agent_id_raises_on_save(
        self, tmp_dir: Path, agent_state: AgentState
    ) -> None:
        db_path = tmp_dir / "test.db"
        store = SQLiteAgentStateStore(db_path)
        with pytest.raises(StoreError, match="agent_id must be non-empty"):
            store.save("", agent_state)

    def test_empty_agent_id_raises_on_load(self, tmp_dir: Path) -> None:
        db_path = tmp_dir / "test.db"
        store = SQLiteAgentStateStore(db_path)
        with pytest.raises(StoreError, match="agent_id must be non-empty"):
            store.load("")

    def test_db_file_created_automatically(self, tmp_dir: Path, agent_state: AgentState) -> None:
        db_path = tmp_dir / "auto_create.db"
        store = SQLiteAgentStateStore(db_path)
        store.save("test-agent", agent_state)
        assert db_path.exists()
        assert db_path.stat().st_size > 0

    def test_persistence_across_store_instances(
        self, tmp_dir: Path, agent_state: AgentState
    ) -> None:
        """Data should survive creating a new store instance pointing at the same file."""
        db_path = tmp_dir / "shared.db"

        store_a = SQLiteAgentStateStore(db_path)
        store_a.save("test-agent", agent_state)

        store_b = SQLiteAgentStateStore(db_path)
        loaded = store_b.load("test-agent")
        assert loaded is not None
        assert loaded.agent_id == "test-agent"
        assert loaded.lifecycle_state == LifecycleState.CREATED

    def test_corrupted_blob_raises(self, tmp_dir: Path) -> None:
        """If the blob column contains invalid JSON, load should raise StoreError."""
        import sqlite3
        from contextlib import closing

        db_path = tmp_dir / "corrupt.db"
        store = SQLiteAgentStateStore(db_path)

        # Manually insert a corrupted blob
        with closing(sqlite3.connect(str(db_path))) as conn:
            conn.execute(
                "INSERT INTO agent_state (agent_id, version, schema_version, "
                "blob, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("bad-agent", 1, 1, "{bad json", "now", "now"),
            )
            conn.commit()

        with pytest.raises(StoreError, match="failed to deserialise"):
            store.load("bad-agent")

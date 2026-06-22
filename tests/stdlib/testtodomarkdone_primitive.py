"""Tests for stdlib.todo.mark_done primitive (Phase 12a.13)."""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from src.capabilities.primitives.stdlib.todo_mark_done import TodoMarkDonePrimitive
from src.capabilities.planner.todo_store import TodoStore


@pytest.fixture
def db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return path


@pytest.fixture
def primitive() -> TodoMarkDonePrimitive:
    return TodoMarkDonePrimitive()


class TestTodoMarkDonePrimitive:
    """Tests for TodoMarkDonePrimitive.validate_args and execute."""

    def test_missing_id_raises(self, primitive: TodoMarkDonePrimitive) -> None:
        with pytest.raises(ValueError, match="'id'"):
            primitive.validate_args({"db_path": "/tmp/x.db"})

    def test_missing_db_path_raises(self, primitive: TodoMarkDonePrimitive) -> None:
        with pytest.raises(ValueError, match="'db_path'"):
            primitive.validate_args({"id": "task-1"})

    def test_mark_done_success(self, primitive: TodoMarkDonePrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.ensure_tables()
        store.add_todo("task-1", "Task One")
        conn.close()

        result = primitive.execute({"id": "task-1", "db_path": db_path}, {})
        assert result.status == "success"
        assert result.data["id"] == "task-1"
        assert result.data["status"] == "done"
        assert result.data["is_complete"] is True

        # Verify in DB
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM todos WHERE id='task-1'").fetchone()
        conn.close()
        assert row["status"] == "done"
        os.unlink(db_path)

    def test_mark_done_not_final_if_others_pending(self, primitive: TodoMarkDonePrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.ensure_tables()
        store.add_todo("task-1", "Task One")
        store.add_todo("task-2", "Task Two")
        conn.close()

        result = primitive.execute({"id": "task-1", "db_path": db_path}, {})
        assert result.status == "success"
        assert result.data["is_complete"] is False
        assert result.data["status_counts"]["done"] == 1
        assert result.data["status_counts"]["pending"] == 1
        os.unlink(db_path)

    def test_nonexistent_id_returns_error(self, primitive: TodoMarkDonePrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        TodoStore(conn).ensure_tables()
        conn.close()

        result = primitive.execute({"id": "nope", "db_path": db_path}, {})
        assert result.status == "error"
        os.unlink(db_path)

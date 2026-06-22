"""Tests for stdlib.todo.mark_failed primitive (Phase 12a.13)."""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from src.capabilities.primitives.stdlib.todo_mark_failed import TodoMarkFailedPrimitive
from src.capabilities.planner.todo_store import TodoStore


@pytest.fixture
def db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return path


@pytest.fixture
def primitive() -> TodoMarkFailedPrimitive:
    return TodoMarkFailedPrimitive()


class TestTodoMarkFailedPrimitive:
    """Tests for TodoMarkFailedPrimitive.validate_args and execute."""

    def test_missing_id_raises(self, primitive: TodoMarkFailedPrimitive) -> None:
        with pytest.raises(ValueError, match="'id'"):
            primitive.validate_args({"db_path": "/tmp/x.db"})

    def test_missing_db_path_raises(self, primitive: TodoMarkFailedPrimitive) -> None:
        with pytest.raises(ValueError, match="'db_path'"):
            primitive.validate_args({"id": "task-1"})

    def test_first_failure_retries_queued(self, primitive: TodoMarkFailedPrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.ensure_tables()
        store.add_todo("task-1", "Task One", retries_remaining=3)
        conn.close()

        result = primitive.execute({"id": "task-1", "db_path": db_path, "error": "Something went wrong"}, {})
        assert result.status == "success"
        assert result.data["retries_exhausted"] is False
        assert "Retry queued" in result.data["message"]
        assert result.data["status"] == "pending"

        # Verify retries decremented
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT retries_remaining FROM todos WHERE id='task-1'").fetchone()
        conn.close()
        assert row["retries_remaining"] == 2
        os.unlink(db_path)

    def test_retries_exhausted(self, primitive: TodoMarkFailedPrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.ensure_tables()
        store.add_todo("task-1", "Task One", retries_remaining=1)
        conn.close()

        result = primitive.execute({"id": "task-1", "db_path": db_path, "error": "Fatal error"}, {})
        assert result.status == "success"
        assert result.data["retries_exhausted"] is True
        assert "Retries exhausted" in result.data["message"]
        assert result.data["status"] == "failed"
        os.unlink(db_path)

    def test_no_error_message_ok(self, primitive: TodoMarkFailedPrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.ensure_tables()
        store.add_todo("task-1", "Task One", retries_remaining=3)
        conn.close()

        result = primitive.execute({"id": "task-1", "db_path": db_path}, {})
        assert result.status == "success"
        os.unlink(db_path)

"""Tests for stdlib.todo.mark_blocked primitive (Phase 12a.13)."""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from src.capabilities.primitives.stdlib.todo_mark_blocked import TodoMarkBlockedPrimitive
from src.capabilities.planner.todo_store import TodoStore


@pytest.fixture
def db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return path


@pytest.fixture
def primitive() -> TodoMarkBlockedPrimitive:
    return TodoMarkBlockedPrimitive()


class TestTodoMarkBlockedPrimitive:
    """Tests for TodoMarkBlockedPrimitive.validate_args and execute."""

    def test_missing_id_raises(self, primitive: TodoMarkBlockedPrimitive) -> None:
        with pytest.raises(ValueError, match="'id'"):
            primitive.validate_args({"db_path": "/tmp/x.db"})

    def test_missing_db_path_raises(self, primitive: TodoMarkBlockedPrimitive) -> None:
        with pytest.raises(ValueError, match="'db_path'"):
            primitive.validate_args({"id": "task-1"})

    def test_mark_blocked_with_reason(self, primitive: TodoMarkBlockedPrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.ensure_tables()
        store.add_todo("task-1", "Task One")
        conn.close()

        result = primitive.execute(
            {"id": "task-1", "db_path": db_path, "reason": "Waiting for API credentials"},
            {},
        )
        assert result.status == "success"
        assert result.data["id"] == "task-1"
        assert result.data["status"] == "blocked"
        assert result.data["reason"] == "Waiting for API credentials"

        # Verify in DB
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM todos WHERE id='task-1'").fetchone()
        conn.close()
        assert row["status"] == "blocked"
        os.unlink(db_path)

    def test_mark_blocked_no_reason(self, primitive: TodoMarkBlockedPrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.ensure_tables()
        store.add_todo("task-1", "Task One")
        conn.close()

        result = primitive.execute({"id": "task-1", "db_path": db_path}, {})
        assert result.status == "success"
        assert result.data["status"] == "blocked"
        assert result.data["reason"] == ""
        os.unlink(db_path)

    def test_blocked_item_not_returned_by_get_next(self, primitive: TodoMarkBlockedPrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.ensure_tables()
        store.add_todo("task-1", "Task One")
        conn.close()

        primitive.execute({"id": "task-1", "db_path": db_path}, {})

        # Verify blocked item isn't returned as next pending
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store2 = TodoStore(conn)
        next_item = store2.get_next_pending()
        conn.close()
        assert next_item is None
        os.unlink(db_path)

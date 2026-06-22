"""Tests for stdlib.todo.get_next primitive (Phase 12a.13)."""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from src.capabilities.primitives.stdlib.todo_get_next import TodoGetNextPrimitive
from src.capabilities.planner.todo_store import TodoStore


@pytest.fixture
def db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return path


@pytest.fixture
def primitive() -> TodoGetNextPrimitive:
    return TodoGetNextPrimitive()


class TestTodoGetNextPrimitive:
    """Tests for TodoGetNextPrimitive.validate_args and execute."""

    def test_missing_db_path_raises(self, primitive: TodoGetNextPrimitive) -> None:
        with pytest.raises(ValueError, match="'db_path'"):
            primitive.validate_args({})

    def test_empty_db_returns_null(self, primitive: TodoGetNextPrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        TodoStore(conn).ensure_tables()
        conn.close()
        result = primitive.execute({"db_path": db_path}, {})
        assert result.status == "success"
        assert result.data["next"] is None
        assert result.data["has_work_remaining"] is False
        os.unlink(db_path)

    def test_returns_first_pending(self, primitive: TodoGetNextPrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.ensure_tables()
        store.add_todo("task-1", "First Task")
        store.add_todo("task-2", "Second Task")
        conn.close()

        result = primitive.execute({"db_path": db_path}, {})
        assert result.status == "success"
        assert result.data["next"] is not None
        assert result.data["next"]["id"] == "task-1"
        assert result.data["next"]["status"] == "pending"
        os.unlink(db_path)

    def test_blocked_item_not_returned(self, primitive: TodoGetNextPrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.ensure_tables()
        store.add_todo("blocker", "Blocker")
        store.add_todo("blocked", "Blocked")
        store.add_dep("blocked", "blocker")
        conn.close()

        result = primitive.execute({"db_path": db_path}, {})
        assert result.status == "success"
        # The blocker (no deps) should be returned; blocked should not
        assert result.data["next"]["id"] == "blocker"
        os.unlink(db_path)

    def test_done_item_excluded(self, primitive: TodoGetNextPrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.ensure_tables()
        store.add_todo("done-task", "Done")
        store.mark_done("done-task")
        conn.close()

        result = primitive.execute({"db_path": db_path}, {})
        assert result.status == "success"
        assert result.data["next"] is None
        os.unlink(db_path)

    def test_all_blocked_returns_null(self, primitive: TodoGetNextPrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.ensure_tables()
        store.add_todo("a", "Task A")
        store.add_todo("b", "Task B")
        store.add_dep("b", "a")  # b depends on a, but a is pending
        conn.close()

        # Both are pending but a has no deps → it should be returned
        result = primitive.execute({"db_path": db_path}, {})
        assert result.data["next"] is not None
        assert result.data["next"]["id"] == "a"
        os.unlink(db_path)

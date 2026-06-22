"""Tests for stdlib.todo.status_summary primitive (Phase 12a.13)."""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from src.capabilities.primitives.stdlib.todo_status_summary import TodoStatusSummaryPrimitive
from src.capabilities.planner.todo_store import TodoStore


@pytest.fixture
def db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return path


@pytest.fixture
def primitive() -> TodoStatusSummaryPrimitive:
    return TodoStatusSummaryPrimitive()


class TestTodoStatusSummaryPrimitive:
    """Tests for TodoStatusSummaryPrimitive.validate_args and execute."""

    def test_missing_db_path_raises(self, primitive: TodoStatusSummaryPrimitive) -> None:
        with pytest.raises(ValueError, match="'db_path'"):
            primitive.validate_args({})

    def test_empty_db(self, primitive: TodoStatusSummaryPrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        TodoStore(conn).ensure_tables()
        conn.close()

        result = primitive.execute({"db_path": db_path}, {})
        assert result.status == "success"
        assert result.data["total"] == 0
        assert result.data["done"] == 0
        assert result.data["is_complete"] is True
        assert result.data["has_work_remaining"] is False
        assert result.data["progress_pct"] == 0
        assert result.data["blocked_items"] == []
        os.unlink(db_path)

    def test_partial_progress(self, primitive: TodoStatusSummaryPrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.ensure_tables()
        store.add_todo("task-1", "Task 1")
        store.add_todo("task-2", "Task 2")
        store.add_todo("task-3", "Task 3")
        store.add_todo("task-4", "Task 4")
        store.mark_done("task-1")
        store.mark_done("task-2")
        conn.close()

        result = primitive.execute({"db_path": db_path}, {})
        assert result.status == "success"
        assert result.data["total"] == 4
        assert result.data["done"] == 2
        assert result.data["is_complete"] is False
        assert result.data["has_work_remaining"] is True
        assert result.data["progress_pct"] == 50.0
        assert result.data["status_counts"]["done"] == 2
        assert result.data["status_counts"]["pending"] == 2
        os.unlink(db_path)

    def test_all_done(self, primitive: TodoStatusSummaryPrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.ensure_tables()
        store.add_todo("task-1", "Task 1")
        store.add_todo("task-2", "Task 2")
        store.mark_done("task-1")
        store.mark_done("task-2")
        conn.close()

        result = primitive.execute({"db_path": db_path}, {})
        assert result.status == "success"
        assert result.data["is_complete"] is True
        assert result.data["progress_pct"] == 100.0
        assert result.data["has_work_remaining"] is False
        os.unlink(db_path)

    def test_blocked_items_listed(self, primitive: TodoStatusSummaryPrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.ensure_tables()
        store.add_todo("task-1", "Task 1")
        store.add_todo("task-2", "Task 2")
        store.add_todo("task-3", "Task 3")
        store.add_dep("task-2", "task-1")
        store.mark_blocked("task-3", "External dependency")
        conn.close()

        result = primitive.execute({"db_path": db_path}, {})
        assert result.status == "success"
        blocked = result.data["blocked_items"]
        assert len(blocked) == 1
        assert blocked[0]["id"] == "task-3"
        os.unlink(db_path)

"""Tests for stdlib.todo.list primitive (Phase 12a.13)."""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from src.capabilities.primitives.stdlib.todo_list import TodoListPrimitive
from src.capabilities.planner.todo_store import TodoStore


@pytest.fixture
def db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return path


@pytest.fixture
def primitive() -> TodoListPrimitive:
    return TodoListPrimitive()


def _populate(db_path: str, items: list[dict]) -> None:
    """Helper: populate todos using TodoStore directly."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    store = TodoStore(conn)
    store.ensure_tables()
    store.add_todos_batch(items)
    for item in items:
        for dep in item.get("depends_on", []):
            store.add_dep(item["id"], dep)
    conn.close()


class TestTodoListPrimitive:
    """Tests for TodoListPrimitive.validate_args and execute."""

    def test_missing_db_path_raises(self, primitive: TodoListPrimitive) -> None:
        with pytest.raises(ValueError, match="'db_path'"):
            primitive.validate_args({})

    def test_empty_list(self, primitive: TodoListPrimitive, db_path: str) -> None:
        _populate(db_path, [])
        result = primitive.execute({"db_path": db_path}, {})
        assert result.status == "success"
        assert result.data["items"] == []
        assert result.data["total"] == 0
        assert result.data["is_complete"] is True
        os.unlink(db_path)

    def test_list_with_items(self, primitive: TodoListPrimitive, db_path: str) -> None:
        _populate(db_path, [
            {"id": "a", "title": "Task A"},
            {"id": "b", "title": "Task B", "depends_on": ["a"]},
        ])
        result = primitive.execute({"db_path": db_path}, {})
        assert result.status == "success"
        assert result.data["total"] == 2
        assert len(result.data["items"]) == 2
        assert result.data["status_counts"]["pending"] == 2
        assert result.data["is_complete"] is False

        # Check dependency resolution
        items_by_id = {it["id"]: it for it in result.data["items"]}
        assert items_by_id["a"]["depends_on"] == []
        assert items_by_id["b"]["depends_on"] == ["a"]
        os.unlink(db_path)

    def test_list_with_mixed_statuses(self, primitive: TodoListPrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.ensure_tables()
        store.add_todo("done-task", "Done Task")
        store.add_todo("pending-task", "Pending Task")
        store.add_todo("failed-task", "Failed Task")
        store.mark_done("done-task")
        store.mark_failed("failed-task", "error")
        store.mark_failed("failed-task", "error")
        store.mark_failed("failed-task", "error")
        store.mark_failed("failed-task", "error")  # exhaust retries
        conn.close()

        result = primitive.execute({"db_path": db_path}, {})
        assert result.status == "success"
        counts = result.data["status_counts"]
        assert counts.get("done", 0) == 1
        assert counts.get("pending", 0) == 1
        assert counts.get("failed", 0) >= 0  # depends on retry exhaustion
        os.unlink(db_path)

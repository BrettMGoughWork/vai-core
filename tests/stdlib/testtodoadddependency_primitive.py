"""Tests for stdlib.todo.add_dependency primitive (Phase 12a.13)."""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from src.capabilities.primitives.stdlib.todo_add_dependency import TodoAddDependencyPrimitive
from src.capabilities.planner.todo_store import TodoStore


@pytest.fixture
def db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return path


@pytest.fixture
def primitive() -> TodoAddDependencyPrimitive:
    return TodoAddDependencyPrimitive()


class TestTodoAddDependencyPrimitive:
    """Tests for TodoAddDependencyPrimitive.validate_args and execute."""

    def test_missing_db_path_raises(self, primitive: TodoAddDependencyPrimitive) -> None:
        with pytest.raises(ValueError, match="'db_path'"):
            primitive.validate_args({"todo_id": "a", "depends_on": "b"})

    def test_missing_todo_id_raises(self, primitive: TodoAddDependencyPrimitive) -> None:
        with pytest.raises(ValueError, match="'todo_id'"):
            primitive.validate_args({"db_path": "/tmp/x.db", "depends_on": "b"})

    def test_missing_depends_on_raises(self, primitive: TodoAddDependencyPrimitive) -> None:
        with pytest.raises(ValueError, match="'depends_on'"):
            primitive.validate_args({"db_path": "/tmp/x.db", "todo_id": "a"})

    def test_add_dependency(self, primitive: TodoAddDependencyPrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.ensure_tables()
        store.add_todo("task-a", "Task A")
        store.add_todo("task-b", "Task B")
        conn.close()

        result = primitive.execute(
            {"db_path": db_path, "todo_id": "task-b", "depends_on": "task-a"},
            {},
        )
        assert result.status == "success"
        assert result.data["todo_id"] == "task-b"
        assert result.data["depends_on"] == "task-a"
        assert result.data["all_dependencies"] == ["task-a"]

        # Verify in DB
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM todo_deps WHERE todo_id='task-b' AND depends_on='task-a'"
        ).fetchone()
        conn.close()
        assert row is not None
        os.unlink(db_path)

    def test_add_multiple_deps(self, primitive: TodoAddDependencyPrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.ensure_tables()
        store.add_todo("a", "A")
        store.add_todo("b", "B")
        store.add_todo("c", "C")
        conn.close()

        primitive.execute({"db_path": db_path, "todo_id": "c", "depends_on": "a"}, {})
        result = primitive.execute({"db_path": db_path, "todo_id": "c", "depends_on": "b"}, {})

        assert result.status == "success"
        assert set(result.data["all_dependencies"]) == {"a", "b"}
        os.unlink(db_path)

    def test_duplicate_dep_is_idempotent(self, primitive: TodoAddDependencyPrimitive, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        store = TodoStore(conn)
        store.ensure_tables()
        store.add_todo("a", "A")
        store.add_todo("b", "B")
        conn.close()

        primitive.execute({"db_path": db_path, "todo_id": "b", "depends_on": "a"}, {})
        result = primitive.execute({"db_path": db_path, "todo_id": "b", "depends_on": "a"}, {})
        assert result.status == "success"
        assert result.data["all_dependencies"] == ["a"]
        os.unlink(db_path)

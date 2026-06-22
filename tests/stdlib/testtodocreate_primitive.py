"""Tests for stdlib.todo.create primitive (Phase 12a.13)."""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from src.capabilities.primitives.stdlib.todo_create import TodoCreatePrimitive


@pytest.fixture
def db_path() -> str:
    """Create a temp file path for the test database (not the file itself)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return path


@pytest.fixture
def primitive() -> TodoCreatePrimitive:
    return TodoCreatePrimitive()


class TestTodoCreatePrimitive:
    """Tests for TodoCreatePrimitive.validate_args and execute."""

    # -- validate_args --

    def test_missing_id_raises(self, primitive: TodoCreatePrimitive) -> None:
        with pytest.raises(ValueError, match="'id'"):
            primitive.validate_args({"title": "Test", "db_path": "/tmp/x.db"})

    def test_missing_title_raises(self, primitive: TodoCreatePrimitive) -> None:
        with pytest.raises(ValueError, match="'title'"):
            primitive.validate_args({"id": "my-todo", "db_path": "/tmp/x.db"})

    def test_missing_db_path_raises(self, primitive: TodoCreatePrimitive) -> None:
        with pytest.raises(ValueError, match="'db_path'"):
            primitive.validate_args({"id": "my-todo", "title": "Test"})

    def test_args_not_dict_raises(self, primitive: TodoCreatePrimitive) -> None:
        with pytest.raises(ValueError, match="dict"):
            primitive.validate_args(["not", "a", "dict"])

    # -- execute --

    def test_create_single_todo(self, primitive: TodoCreatePrimitive, db_path: str) -> None:
        result = primitive.execute(
            {"id": "task-1", "title": "Do something", "db_path": db_path},
            {},
        )
        assert result.status == "success"
        assert result.data["id"] == "task-1"
        assert result.data["status"] == "pending"

        # Verify it's actually in the database
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM todos WHERE id='task-1'").fetchone()
        conn.close()
        assert row is not None
        assert row["title"] == "Do something"
        assert row["status"] == "pending"
        os.unlink(db_path)

    def test_create_with_description(self, primitive: TodoCreatePrimitive, db_path: str) -> None:
        result = primitive.execute(
            {"id": "task-2", "title": "Test", "description": "A detailed description", "db_path": db_path},
            {},
        )
        assert result.status == "success"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT description FROM todos WHERE id='task-2'").fetchone()
        conn.close()
        assert row["description"] == "A detailed description"
        os.unlink(db_path)

    def test_create_with_custom_retries(self, primitive: TodoCreatePrimitive, db_path: str) -> None:
        result = primitive.execute(
            {"id": "task-3", "title": "Test", "retries_remaining": 5, "db_path": db_path},
            {},
        )
        assert result.status == "success"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT retries_remaining FROM todos WHERE id='task-3'").fetchone()
        conn.close()
        assert row["retries_remaining"] == 5
        os.unlink(db_path)

    def test_duplicate_id_returns_error(self, primitive: TodoCreatePrimitive, db_path: str) -> None:
        primitive.execute({"id": "dup", "title": "First", "db_path": db_path}, {})
        result = primitive.execute({"id": "dup", "title": "Second", "db_path": db_path}, {})
        assert result.status == "error"
        assert "already exists" in result.error
        os.unlink(db_path)

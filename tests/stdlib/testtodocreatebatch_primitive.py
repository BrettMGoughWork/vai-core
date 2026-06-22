"""Tests for stdlib.todo.create_batch primitive (Phase 12a.13)."""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from src.capabilities.primitives.stdlib.todo_create_batch import TodoCreateBatchPrimitive


@pytest.fixture
def db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    return path


@pytest.fixture
def primitive() -> TodoCreateBatchPrimitive:
    return TodoCreateBatchPrimitive()


class TestTodoCreateBatchPrimitive:
    """Tests for TodoCreateBatchPrimitive.validate_args and execute."""

    # -- validate_args --

    def test_missing_db_path_raises(self, primitive: TodoCreateBatchPrimitive) -> None:
        with pytest.raises(ValueError, match="'db_path'"):
            primitive.validate_args({"items": [{"id": "a", "title": "A"}]})

    def test_missing_items_raises(self, primitive: TodoCreateBatchPrimitive) -> None:
        with pytest.raises(ValueError, match="'items'"):
            primitive.validate_args({"db_path": "/tmp/x.db"})

    def test_items_not_list_raises(self, primitive: TodoCreateBatchPrimitive) -> None:
        with pytest.raises(ValueError, match="non-empty list"):
            primitive.validate_args({"db_path": "/tmp/x.db", "items": "not-a-list"})

    def test_empty_items_raises(self, primitive: TodoCreateBatchPrimitive) -> None:
        with pytest.raises(ValueError, match="non-empty list"):
            primitive.validate_args({"db_path": "/tmp/x.db", "items": []})

    def test_item_not_dict_raises(self, primitive: TodoCreateBatchPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a dict"):
            primitive.validate_args({"db_path": "/tmp/x.db", "items": ["not-dict"]})

    def test_item_missing_id_raises(self, primitive: TodoCreateBatchPrimitive) -> None:
        with pytest.raises(ValueError, match="'id'"):
            primitive.validate_args({"db_path": "/tmp/x.db", "items": [{"title": "No ID"}]})

    def test_item_missing_title_raises(self, primitive: TodoCreateBatchPrimitive) -> None:
        with pytest.raises(ValueError, match="'title'"):
            primitive.validate_args({"db_path": "/tmp/x.db", "items": [{"id": "no-title"}]})

    # -- execute --

    def test_create_batch_no_deps(self, primitive: TodoCreateBatchPrimitive, db_path: str) -> None:
        result = primitive.execute(
            {
                "db_path": db_path,
                "items": [
                    {"id": "task-a", "title": "Task A"},
                    {"id": "task-b", "title": "Task B"},
                ],
            },
            {},
        )
        assert result.status == "success"
        assert result.data["created"] == 2
        assert result.data["dependencies_added"] == 0
        assert set(result.data["ids"]) == {"task-a", "task-b"}

        # Verify in database
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, status FROM todos ORDER BY id").fetchall()
        conn.close()
        assert len(rows) == 2
        assert all(r["status"] == "pending" for r in rows)
        os.unlink(db_path)

    def test_create_batch_with_deps(self, primitive: TodoCreateBatchPrimitive, db_path: str) -> None:
        result = primitive.execute(
            {
                "db_path": db_path,
                "items": [
                    {"id": "design-db", "title": "Design DB"},
                    {"id": "write-models", "title": "Write Models", "depends_on": ["design-db"]},
                    {"id": "write-routes", "title": "Write Routes", "depends_on": ["write-models"]},
                ],
            },
            {},
        )
        assert result.status == "success"
        assert result.data["created"] == 3
        assert result.data["dependencies_added"] == 2

        # Verify deps
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        deps = conn.execute("SELECT todo_id, depends_on FROM todo_deps ORDER BY todo_id").fetchall()
        conn.close()
        assert len(deps) == 2
        dep_map = {d["todo_id"]: d["depends_on"] for d in deps}
        assert dep_map["write-models"] == "design-db"
        assert dep_map["write-routes"] == "write-models"
        os.unlink(db_path)

    def test_batch_with_descriptions(self, primitive: TodoCreateBatchPrimitive, db_path: str) -> None:
        result = primitive.execute(
            {
                "db_path": db_path,
                "items": [
                    {"id": "task-1", "title": "Task 1", "description": "First task description"},
                    {"id": "task-2", "title": "Task 2", "description": "Second task description"},
                ],
            },
            {},
        )
        assert result.status == "success"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, description FROM todos ORDER BY id").fetchall()
        conn.close()
        assert rows[0]["description"] == "First task description"
        assert rows[1]["description"] == "Second task description"
        os.unlink(db_path)

    def test_duplicate_id_returns_error(self, primitive: TodoCreateBatchPrimitive, db_path: str) -> None:
        primitive.execute(
            {"db_path": db_path, "items": [{"id": "dup", "title": "First"}]},
            {},
        )
        result = primitive.execute(
            {"db_path": db_path, "items": [{"id": "dup", "title": "Second"}]},
            {},
        )
        assert result.status == "error"
        assert "IntegrityError" in result.error
        os.unlink(db_path)

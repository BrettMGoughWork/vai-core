"""Tests for stdlib.db.update primitive (Phase 3.18.4)."""

from __future__ import annotations

import sqlite3

import pytest

from src.capabilities.primitives.stdlib.db_update import DbUpdatePrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def connected_context() -> dict:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)")
    conn.execute("INSERT INTO users (name, age) VALUES ('Alice', 30)")
    conn.execute("INSERT INTO users (name, age) VALUES ('Bob', 25)")
    conn.commit()
    return {"db_connection": conn}


@pytest.fixture
def db_update() -> DbUpdatePrimitive:
    return DbUpdatePrimitive()


class TestDbUpdatePrimitive:
    """Tests for DbUpdatePrimitive.validate_args and execute."""

    def test_update_single_row(self, db_update: DbUpdatePrimitive, connected_context: dict) -> None:
        """Update a single row by condition."""
        result = db_update.execute(
            {"table": "users", "set": {"age": 31}, "where": {"name": "Alice"}},
            connected_context,
        )
        assert result.status == "success"
        assert result.data["updated"] == 1

    def test_update_multiple_rows(self, db_update: DbUpdatePrimitive, connected_context: dict) -> None:
        """Update with empty where updates all rows."""
        result = db_update.execute(
            {"table": "users", "set": {"age": 99}, "where": {}},
            connected_context,
        )
        assert result.status == "success"
        assert result.data["updated"] == 2

    def test_no_connection_returns_error(self, db_update: DbUpdatePrimitive) -> None:
        result = db_update.execute({"table": "users", "set": {"x": 1}, "where": {}}, {})
        assert result.status == "error"
        assert "No database connection" in result.error

    def test_missing_table_raises_value_error(self, db_update: DbUpdatePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'table' key"):
            db_update.validate_args({"set": {"a": 1}, "where": {}})

    def test_missing_set_raises_value_error(self, db_update: DbUpdatePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'set' key"):
            db_update.validate_args({"table": "t", "where": {}})

    def test_missing_where_raises_value_error(self, db_update: DbUpdatePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'where' key"):
            db_update.validate_args({"table": "t", "set": {"a": 1}})

    def test_empty_set_raises_value_error(self, db_update: DbUpdatePrimitive) -> None:
        with pytest.raises(ValueError, match="non-empty dict"):
            db_update.validate_args({"table": "t", "set": {}, "where": {}})

    def test_invalid_where_type_raises_value_error(self, db_update: DbUpdatePrimitive) -> None:
        with pytest.raises(ValueError, match="must be a dict"):
            db_update.validate_args({"table": "t", "set": {"a": 1}, "where": "x"})

    def test_invalid_table_returns_error(self, db_update: DbUpdatePrimitive, connected_context: dict) -> None:
        result = db_update.execute(
            {"table": "nonexistent", "set": {"x": 1}, "where": {}},
            connected_context,
        )
        assert result.status == "error"

"""Tests for stdlib.db.delete primitive (Phase 3.18.4)."""

from __future__ import annotations

import sqlite3

import pytest

from src.capabilities.primitives.stdlib.db_delete import DbDeletePrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def connected_context() -> dict:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO users (name) VALUES ('Alice')")
    conn.execute("INSERT INTO users (name) VALUES ('Bob')")
    conn.commit()
    return {"db_connection": conn}


@pytest.fixture
def db_delete() -> DbDeletePrimitive:
    return DbDeletePrimitive()


class TestDbDeletePrimitive:
    """Tests for DbDeletePrimitive.validate_args and execute."""

    def test_delete_with_where(self, db_delete: DbDeletePrimitive, connected_context: dict) -> None:
        """Delete a specific row by condition."""
        result = db_delete.execute(
            {"table": "users", "where": {"name": "Alice"}},
            connected_context,
        )
        assert result.status == "success"
        assert result.data["deleted"] == 1

    def test_delete_all_rows(self, db_delete: DbDeletePrimitive, connected_context: dict) -> None:
        """Delete without where removes all rows."""
        result = db_delete.execute({"table": "users"}, connected_context)
        assert result.status == "success"
        assert result.data["deleted"] == 2

    def test_delete_empty_table(self, db_delete: DbDeletePrimitive, connected_context: dict) -> None:
        """Deleting from empty table returns 0."""
        conn = connected_context["db_connection"]
        conn.execute("DELETE FROM users")
        conn.commit()
        result = db_delete.execute({"table": "users"}, connected_context)
        assert result.status == "success"
        assert result.data["deleted"] == 0

    def test_no_connection_returns_error(self, db_delete: DbDeletePrimitive) -> None:
        result = db_delete.execute({"table": "users"}, {})
        assert result.status == "error"
        assert "No database connection" in result.error

    def test_missing_table_raises_value_error(self, db_delete: DbDeletePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'table' key"):
            db_delete.validate_args({})

    def test_empty_table_raises_value_error(self, db_delete: DbDeletePrimitive) -> None:
        with pytest.raises(ValueError, match="non-empty string"):
            db_delete.validate_args({"table": "  "})

    def test_invalid_where_type_raises_value_error(self, db_delete: DbDeletePrimitive) -> None:
        with pytest.raises(ValueError, match="must be a dict"):
            db_delete.validate_args({"table": "t", "where": "not a dict"})

    def test_nonexistent_table_returns_error(self, db_delete: DbDeletePrimitive, connected_context: dict) -> None:
        result = db_delete.execute({"table": "nonexistent"}, connected_context)
        assert result.status == "error"

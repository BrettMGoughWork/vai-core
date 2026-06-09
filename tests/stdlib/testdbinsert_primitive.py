"""Tests for stdlib.db.insert primitive (Phase 3.18.4)."""

from __future__ import annotations

import sqlite3

import pytest

from src.capabilities.primitives.stdlib.db_insert import DbInsertPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def connected_context() -> dict:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.commit()
    return {"db_connection": conn}


@pytest.fixture
def db_insert() -> DbInsertPrimitive:
    return DbInsertPrimitive()


class TestDbInsertPrimitive:
    """Tests for DbInsertPrimitive.validate_args and execute."""

    def test_insert_single_row(self, db_insert: DbInsertPrimitive, connected_context: dict) -> None:
        """Insert a single row and verify rowcount."""
        result = db_insert.execute(
            {"table": "users", "rows": [{"name": "Alice"}]},
            connected_context,
        )
        assert result.status == "success"
        assert result.data["inserted"] == 1
        # executemany sets lastrowid to None; just verify it's present
        assert "lastrowid" in result.data

    def test_insert_multiple_rows(self, db_insert: DbInsertPrimitive, connected_context: dict) -> None:
        """Insert multiple rows in one call."""
        result = db_insert.execute(
            {"table": "users", "rows": [{"name": "Alice"}, {"name": "Bob"}]},
            connected_context,
        )
        assert result.status == "success"
        assert result.data["inserted"] == 2

    def test_no_connection_returns_error(self, db_insert: DbInsertPrimitive) -> None:
        """Missing connection in context returns error."""
        result = db_insert.execute({"table": "users", "rows": [{"name": "X"}]}, {})
        assert result.status == "error"
        assert "No database connection" in result.error

    def test_missing_table_raises_value_error(self, db_insert: DbInsertPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'table' key"):
            db_insert.validate_args({"rows": [{"a": 1}]})

    def test_missing_rows_raises_value_error(self, db_insert: DbInsertPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'rows' key"):
            db_insert.validate_args({"table": "t"})

    def test_empty_table_raises_value_error(self, db_insert: DbInsertPrimitive) -> None:
        with pytest.raises(ValueError, match="non-empty string"):
            db_insert.validate_args({"table": "  ", "rows": [{"a": 1}]})

    def test_empty_rows_raises_value_error(self, db_insert: DbInsertPrimitive) -> None:
        with pytest.raises(ValueError, match="non-empty list"):
            db_insert.validate_args({"table": "t", "rows": []})

    def test_rows_elements_not_dicts_raises_value_error(self, db_insert: DbInsertPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a dict"):
            db_insert.validate_args({"table": "t", "rows": [42]})

    def test_invalid_table_returns_error(self, db_insert: DbInsertPrimitive, connected_context: dict) -> None:
        """Inserting into nonexistent table returns error."""
        result = db_insert.execute(
            {"table": "nonexistent", "rows": [{"name": "X"}]},
            connected_context,
        )
        assert result.status == "error"

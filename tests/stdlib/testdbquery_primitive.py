"""Tests for stdlib.db.query primitive (Phase 3.18.4)."""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from src.capabilities.primitives.stdlib.db_connect import DbConnectPrimitive
from src.capabilities.primitives.stdlib.db_query import DbQueryPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def connected_context() -> dict:
    """Return a context with an open SQLite connection to an in-memory database."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO users (name) VALUES ('Alice')")
    conn.execute("INSERT INTO users (name) VALUES ('Bob')")
    conn.commit()
    return {"db_connection": conn}


@pytest.fixture
def db_query() -> DbQueryPrimitive:
    return DbQueryPrimitive()


class TestDbQueryPrimitive:
    """Tests for DbQueryPrimitive.validate_args and execute."""

    def test_select_all_rows(self, db_query: DbQueryPrimitive, connected_context: dict) -> None:
        """A SELECT query returns all matching rows."""
        result = db_query.execute({"query": "SELECT * FROM users"}, connected_context)
        assert result.status == "success"
        assert result.data["row_count"] == 2
        assert len(result.data["rows"]) == 2

    def test_select_with_where(self, db_query: DbQueryPrimitive, connected_context: dict) -> None:
        """A SELECT with WHERE clause returns filtered rows."""
        result = db_query.execute({"query": "SELECT * FROM users WHERE name = 'Alice'"}, connected_context)
        assert result.status == "success"
        assert result.data["row_count"] == 1
        assert result.data["rows"][0]["name"] == "Alice"

    def test_select_with_params(self, db_query: DbQueryPrimitive, connected_context: dict) -> None:
        """Parameters are properly substituted."""
        result = db_query.execute(
            {"query": "SELECT * FROM users WHERE name = ?", "params": ("Bob",)},
            connected_context,
        )
        assert result.status == "success"
        assert result.data["row_count"] == 1
        assert result.data["rows"][0]["name"] == "Bob"

    def test_pragma_query(self, db_query: DbQueryPrimitive, connected_context: dict) -> None:
        """PRAGMA queries are allowed."""
        result = db_query.execute({"query": "PRAGMA table_info('users')"}, connected_context)
        assert result.status == "success"
        assert len(result.data["rows"]) >= 2  # id and name columns

    def test_no_connection_returns_error(self, db_query: DbQueryPrimitive) -> None:
        """Missing db_connection in context returns error."""
        result = db_query.execute({"query": "SELECT 1"}, {})
        assert result.status == "error"
        assert "No database connection" in result.error

    def test_dml_rejected(self, db_query: DbQueryPrimitive) -> None:
        """INSERT/UPDATE/DELETE queries are rejected."""
        with pytest.raises(ValueError, match="only allows read-only"):
            db_query.validate_args({"query": "INSERT INTO users (name) VALUES ('Eve')"})

    def test_missing_query_raises_value_error(self, db_query: DbQueryPrimitive) -> None:
        """Missing 'query' key raises ValueError."""
        with pytest.raises(ValueError, match="must contain 'query' key"):
            db_query.validate_args({})

    def test_empty_query_raises_value_error(self, db_query: DbQueryPrimitive) -> None:
        """Empty query raises ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            db_query.validate_args({"query": "  "})

    def test_invalid_sql_returns_error(self, db_query: DbQueryPrimitive, connected_context: dict) -> None:
        """Malformed SQL returns error."""
        result = db_query.execute({"query": "SELECT * FROM nonexistent"}, connected_context)
        assert result.status == "error"

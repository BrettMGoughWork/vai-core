"""Tests for stdlib.db.listtables primitive (Phase 3.18.4)."""

from __future__ import annotations

import sqlite3

import pytest

from src.capabilities.primitives.stdlib.db_listtables import DbListTablesPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def connected_context() -> dict:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY)")
    conn.commit()
    return {"db_connection": conn}


@pytest.fixture
def db_listtables() -> DbListTablesPrimitive:
    return DbListTablesPrimitive()


class TestDbListTablesPrimitive:
    """Tests for DbListTablesPrimitive.validate_args and execute."""

    def test_list_tables(self, db_listtables: DbListTablesPrimitive, connected_context: dict) -> None:
        """Returns all table names in the database."""
        result = db_listtables.execute({}, connected_context)
        assert result.status == "success"
        assert "tables" in result.data
        tables = result.data["tables"]
        assert "users" in tables
        assert "posts" in tables

    def test_empty_database(self, db_listtables: DbListTablesPrimitive) -> None:
        """An empty database returns empty list."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        result = db_listtables.execute({}, {"db_connection": conn})
        assert result.status == "success"
        assert result.data["tables"] == []

    def test_no_connection_returns_error(self, db_listtables: DbListTablesPrimitive) -> None:
        result = db_listtables.execute({}, {})
        assert result.status == "error"
        assert "No database connection" in result.error

    def test_args_not_dict_raises_value_error(self, db_listtables: DbListTablesPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a dict"):
            db_listtables.validate_args("not a dict")

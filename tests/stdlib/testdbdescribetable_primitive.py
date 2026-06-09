"""Tests for stdlib.db.describetable primitive (Phase 3.18.4)."""

from __future__ import annotations

import sqlite3

import pytest

from src.capabilities.primitives.stdlib.db_describetable import DbDescribeTablePrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def connected_context() -> dict:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, age INTEGER DEFAULT 0)")
    conn.commit()
    return {"db_connection": conn}


@pytest.fixture
def db_describetable() -> DbDescribeTablePrimitive:
    return DbDescribeTablePrimitive()


class TestDbDescribeTablePrimitive:
    """Tests for DbDescribeTablePrimitive.validate_args and execute."""

    def test_describe_table(self, db_describetable: DbDescribeTablePrimitive, connected_context: dict) -> None:
        """Returns column info for an existing table."""
        result = db_describetable.execute({"table": "users"}, connected_context)
        assert result.status == "success"
        assert result.data["table"] == "users"
        columns = result.data["columns"]
        assert len(columns) == 3

        col_names = {c["name"] for c in columns}
        assert col_names == {"id", "name", "age"}

        name_col = next(c for c in columns if c["name"] == "name")
        assert name_col["notnull"] is True

        age_col = next(c for c in columns if c["name"] == "age")
        assert age_col["default_value"] == "0"

    def test_nonexistent_table_returns_error(self, db_describetable: DbDescribeTablePrimitive, connected_context: dict) -> None:
        """Describing a nonexistent table returns error."""
        result = db_describetable.execute({"table": "nonexistent"}, connected_context)
        assert result.status == "error"
        assert "not found" in result.error

    def test_no_connection_returns_error(self, db_describetable: DbDescribeTablePrimitive) -> None:
        result = db_describetable.execute({"table": "users"}, {})
        assert result.status == "error"
        assert "No database connection" in result.error

    def test_missing_table_raises_value_error(self, db_describetable: DbDescribeTablePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'table' key"):
            db_describetable.validate_args({})

    def test_empty_table_raises_value_error(self, db_describetable: DbDescribeTablePrimitive) -> None:
        with pytest.raises(ValueError, match="non-empty string"):
            db_describetable.validate_args({"table": "  "})

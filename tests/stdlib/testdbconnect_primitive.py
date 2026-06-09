"""Tests for stdlib.db.connect primitive (Phase 3.18.4)."""

from __future__ import annotations

import os
import tempfile

import pytest

from src.capabilities.primitives.stdlib.db_connect import DbConnectPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def db_connect() -> DbConnectPrimitive:
    return DbConnectPrimitive()


class TestDbConnectPrimitive:
    """Tests for DbConnectPrimitive.validate_args and execute."""

    def test_connect_to_new_file(self, db_connect: DbConnectPrimitive) -> None:
        """Connecting to a new file returns connected=True."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        context: dict = {}
        try:
            result = db_connect.execute({"path": path}, context)
            assert isinstance(result, PrimitiveResult)
            assert result.status == "success"
            assert result.data["connected"] is True
            assert os.path.abspath(path) in result.data["path"]
        finally:
            if "db_connection" in context:
                context["db_connection"].close()
            os.unlink(path)

    def test_connect_to_existing_file(self, db_connect: DbConnectPrimitive) -> None:
        """Connecting to an existing file succeeds."""
        import sqlite3
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        context: dict = {}
        try:
            conn = sqlite3.connect(path)
            conn.execute("CREATE TABLE t (a INTEGER)")
            conn.commit()
            conn.close()
            result = db_connect.execute({"path": path}, context)
            assert result.status == "success"
            assert result.data["connected"] is True
        finally:
            if "db_connection" in context:
                context["db_connection"].close()
            os.unlink(path)

    def test_context_populates_db_connection(self, db_connect: DbConnectPrimitive) -> None:
        """The context dict receives the connection object."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        context: dict = {}
        try:
            result = db_connect.execute({"path": path}, context)
            assert result.status == "success"
            assert "db_connection" in context
            assert context["db_connection"] is not None
        finally:
            if "db_connection" in context:
                context["db_connection"].close()
            os.unlink(path)

    def test_missing_path_raises_value_error(self, db_connect: DbConnectPrimitive) -> None:
        """Missing 'path' key raises ValueError."""
        with pytest.raises(ValueError, match="must contain 'path' key"):
            db_connect.validate_args({})

    def test_path_not_string_raises_value_error(self, db_connect: DbConnectPrimitive) -> None:
        """Non-string path raises ValueError."""
        with pytest.raises(ValueError, match="must be a string"):
            db_connect.validate_args({"path": 42})

    def test_empty_path_raises_value_error(self, db_connect: DbConnectPrimitive) -> None:
        """Empty path raises ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            db_connect.validate_args({"path": ""})

    def test_invalid_path_returns_error(self, db_connect: DbConnectPrimitive) -> None:
        """A path to a directory (not a SQLite file) still connects (SQLite is lenient)."""
        # SQLite creates/opens any file; this is OS-dependent but should succeed
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        context: dict = {}
        try:
            result = db_connect.execute({"path": path}, context)
            assert result.status == "success"
        finally:
            if "db_connection" in context:
                context["db_connection"].close()
            os.unlink(path)

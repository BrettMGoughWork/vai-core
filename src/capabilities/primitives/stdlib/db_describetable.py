"""stdlib.db.describetable — Describe the schema of a table (Phase 3.18.4)."""

from __future__ import annotations

import json
import sqlite3

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


class DbDescribeTablePrimitive(PrimitiveBase):
    """Return the column names and types for a database table."""

    name = "stdlib.db.describetable"
    description = "Describe the schema of a database table"
    primitive_type = PrimitiveType.PYTHON

    def __init__(self) -> None:
        super().__init__(
            name=self.name,
            description=self.description,
            primitive_type=self.primitive_type,
        )

    def validate_args(self, args: dict) -> None:
        if not isinstance(args, dict):
            raise ValueError(f"args must be a dict, got {type(args).__name__}")
        if "table" not in args:
            raise ValueError("args must contain 'table' key")
        table = args["table"]
        if not isinstance(table, str) or not table.strip():
            raise ValueError("'table' must be a non-empty string")
        try:
            json.dumps(table)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"'table' must be JSON-serializable: {exc}") from exc

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        table = args["table"]
        conn = context.get("db_connection")
        if conn is None:
            return PrimitiveResult(
                status="error",
                data=None,
                error="No database connection in context. Call stdlib.db.connect first.",
            )
        try:
            cursor = conn.cursor()
            cursor.execute(f'PRAGMA table_info("{table}")')
            rows = cursor.fetchall()
            if not rows:
                return PrimitiveResult(
                    status="error",
                    data=None,
                    error=f"Table '{table}' not found",
                )
            columns = [
                {
                    "cid": row["cid"],
                    "name": row["name"],
                    "type": row["type"],
                    "notnull": bool(row["notnull"]),
                    "default_value": row["dflt_value"],
                    "primary_key": bool(row["pk"]),
                }
                for row in rows
            ]
            return PrimitiveResult(
                status="success",
                data={"table": table, "columns": columns},
            )
        except sqlite3.Error as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"SQLiteError: {exc}",
            )

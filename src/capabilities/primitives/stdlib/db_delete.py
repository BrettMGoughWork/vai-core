"""stdlib.db.delete — Delete rows from a table (Phase 3.18.4)."""

from __future__ import annotations

import json
import sqlite3

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class DbDeletePrimitive(PrimitiveBase):
    """Delete rows from a database table with a WHERE clause."""

    name = "stdlib.db.delete"
    description = "Delete rows from a database table"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "table": {
                "type": "string",
                "description": "Name of the table to delete rows from",
            },
            "where": {
                "type": "object",
                "description": "WHERE clause as key-value pairs (e.g., {'id': 5})",
            },
        },
        "required": ["table"],
    }

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
        if "where" in args and not isinstance(args["where"], dict):
            raise ValueError("'where' must be a dict if provided")
        try:
            json.dumps(args)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"args must be JSON-serializable: {exc}") from exc

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        table = args["table"]
        where = args.get("where", {})
        conn = context.get("db_connection")
        if conn is None:
            return PrimitiveResult(
                status="error",
                data=None,
                error="No database connection in context. Call stdlib.db.connect first.",
            )
        try:
            if where:
                where_clause = " AND ".join(f'"{col}" = ?' for col in where)
                sql = f'DELETE FROM "{table}" WHERE {where_clause}'
                params = list(where.values())
            else:
                sql = f'DELETE FROM "{table}"'
                params = []
            cursor = conn.cursor()
            cursor.execute(sql, params)
            conn.commit()
            return PrimitiveResult(
                status="success",
                data={"deleted": cursor.rowcount},
            )
        except sqlite3.Error as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"SQLiteError: {exc}",
            )

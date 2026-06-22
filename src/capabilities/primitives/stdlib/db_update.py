"""stdlib.db.update — Update rows in a table (Phase 3.18.4)."""

from __future__ import annotations

import json
import sqlite3

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class DbUpdatePrimitive(PrimitiveBase):
    """Update rows in a database table with a WHERE clause."""

    name = "stdlib.db.update"
    description = "Update rows in a database table"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "table": {
                "type": "string",
                "description": "Name of the table to update rows in",
            },
            "set": {
                "type": "object",
                "description": "Column-value pairs to set (e.g., {'status': 'done'})",
            },
            "where": {
                "type": "object",
                "description": "WHERE clause as key-value pairs (e.g., {'id': 5})",
            },
        },
        "required": ["table", "set", "where"],
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
        if "set" not in args:
            raise ValueError("args must contain 'set' key")
        if "where" not in args:
            raise ValueError("args must contain 'where' key")
        table = args["table"]
        set_vals = args["set"]
        where = args["where"]
        if not isinstance(table, str) or not table.strip():
            raise ValueError("'table' must be a non-empty string")
        if not isinstance(set_vals, dict) or len(set_vals) == 0:
            raise ValueError("'set' must be a non-empty dict")
        if not isinstance(where, dict):
            raise ValueError("'where' must be a dict")
        try:
            json.dumps({"table": table, "set": set_vals, "where": where})
        except (TypeError, ValueError) as exc:
            raise ValueError(f"args must be JSON-serializable: {exc}") from exc

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        table = args["table"]
        set_vals = args["set"]
        where = args["where"]
        conn = context.get("db_connection")
        if conn is None:
            return PrimitiveResult(
                status="error",
                data=None,
                error="No database connection in context. Call stdlib.db.connect first.",
            )
        try:
            set_clause = ", ".join(f'"{col}" = ?' for col in set_vals)
            set_params = list(set_vals.values())
            if where:
                where_clause = " AND ".join(f'"{col}" = ?' for col in where)
                where_params = list(where.values())
                sql = f'UPDATE "{table}" SET {set_clause} WHERE {where_clause}'
                params = set_params + where_params
            else:
                sql = f'UPDATE "{table}" SET {set_clause}'
                params = set_params
            cursor = conn.cursor()
            cursor.execute(sql, params)
            conn.commit()
            return PrimitiveResult(
                status="success",
                data={"updated": cursor.rowcount},
            )
        except sqlite3.Error as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"SQLiteError: {exc}",
            )

"""stdlib.db.insert — Insert a row into a table (Phase 3.18.4)."""

from __future__ import annotations

import json
import sqlite3

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class DbInsertPrimitive(PrimitiveBase):
    """Insert one or more rows into a database table."""

    name = "stdlib.db.insert"
    description = "Insert rows into a database table"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "table": {
                "type": "string",
                "description": "Name of the table to insert rows into",
            },
            "rows": {
                "type": "array",
                "description": "List of row objects (dicts) to insert",
                "items": {
                    "type": "object",
                },
            },
        },
        "required": ["table", "rows"],
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
        if "rows" not in args:
            raise ValueError("args must contain 'rows' key")
        table = args["table"]
        rows = args["rows"]
        if not isinstance(table, str) or not table.strip():
            raise ValueError("'table' must be a non-empty string")
        if not isinstance(rows, list) or len(rows) == 0:
            raise ValueError("'rows' must be a non-empty list of dicts")
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"rows[{i}] must be a dict, got {type(row).__name__}")
        try:
            json.dumps({"table": table, "rows": rows})
        except (TypeError, ValueError) as exc:
            raise ValueError(f"args must be JSON-serializable: {exc}") from exc

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        table = args["table"]
        rows = args["rows"]
        conn = context.get("db_connection")
        if conn is None:
            return PrimitiveResult(
                status="error",
                data=None,
                error="No database connection in context. Call stdlib.db.connect first.",
            )
        try:
            columns = list(rows[0].keys())
            placeholders = ", ".join("?" for _ in columns)
            col_names = ", ".join(columns)
            sql = f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders})'
            cursor = conn.cursor()
            cursor.executemany(sql, [tuple(row[col] for col in columns) for row in rows])
            conn.commit()
            return PrimitiveResult(
                status="success",
                data={"inserted": cursor.rowcount, "lastrowid": cursor.lastrowid},
            )
        except sqlite3.Error as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"SQLiteError: {exc}",
            )

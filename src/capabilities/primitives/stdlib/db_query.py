"""stdlib.db.query — Run a SQL SELECT query (Phase 3.18.4)."""

from __future__ import annotations

import json
import sqlite3

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class DbQueryPrimitive(PrimitiveBase):
    """Run a read-only SQL SELECT query against an open database connection."""

    name = "stdlib.db.query"
    description = "Execute a read-only SQL SELECT query"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "SQL SELECT query to execute against the open database connection",
            },
            "params": {
                "type": "array",
                "description": "Query parameters for parameterized queries",
            },
        },
        "required": ["query"],
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
        if "query" not in args:
            raise ValueError("args must contain 'query' key")
        query = args["query"]
        if not isinstance(query, str):
            raise ValueError(f"'query' must be a string, got {type(query).__name__}")
        if not query.strip():
            raise ValueError("'query' must not be empty")
        upper = query.strip().upper()
        if not upper.startswith("SELECT") and not upper.startswith("PRAGMA") and not upper.startswith("EXPLAIN"):
            raise ValueError("db.query only allows read-only statements (SELECT/PRAGMA/EXPLAIN)")
        try:
            json.dumps(query)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"'query' must be JSON-serializable: {exc}") from exc

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        query = args["query"]
        params = args.get("params", ())
        conn = context.get("db_connection")
        if conn is None:
            return PrimitiveResult(
                status="error",
                data=None,
                error="No database connection in context. Call stdlib.db.connect first.",
            )
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = [dict(row) for row in cursor.fetchall()]
            return PrimitiveResult(
                status="success",
                data={"rows": rows, "row_count": len(rows)},
            )
        except sqlite3.Error as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"SQLiteError: {exc}",
            )

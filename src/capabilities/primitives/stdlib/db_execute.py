"""stdlib.db.execute — Execute DDL statements against a SQLite database (Phase 12a.1).

Security: DDL only (CREATE TABLE, DROP, ALTER, CREATE INDEX).
No DML — INSERT/UPDATE/DELETE use their own primitives.
"""

from __future__ import annotations

import json
import sqlite3

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.domain._markers import deadcode_ignore

_DDL_PREFIXES = (
    "CREATE TABLE",
    "CREATE INDEX",
    "CREATE UNIQUE INDEX",
    "CREATE TEMP TABLE",
    "CREATE TEMPORARY TABLE",
    "ALTER TABLE",
    "DROP TABLE",
    "DROP INDEX",
    "DROP VIEW",
    "CREATE VIEW",
    "CREATE TEMP VIEW",
    "CREATE TEMPORARY VIEW",
)


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class DbExecutePrimitive(PrimitiveBase):
    """Execute a DDL statement (CREATE TABLE, DROP, ALTER, CREATE INDEX, etc.)."""

    name = "stdlib.db.execute"
    description = "Execute a DDL statement (CREATE TABLE, DROP, ALTER, CREATE INDEX, etc.)"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "DDL statement to execute (CREATE TABLE, DROP, ALTER, CREATE INDEX, etc.)",
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
        if not any(upper.startswith(prefix) for prefix in _DDL_PREFIXES):
            raise ValueError(
                f"db.execute only allows DDL statements "
                f"(CREATE TABLE/INDEX/VIEW, DROP TABLE/INDEX/VIEW, ALTER TABLE). "
                f"Got: {query[:60]}..."
            )
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
            conn.commit()
            return PrimitiveResult(
                status="success",
                data={"executed": True, "rowcount": cursor.rowcount},
            )
        except sqlite3.Error as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"SQLiteError: {exc}",
            )

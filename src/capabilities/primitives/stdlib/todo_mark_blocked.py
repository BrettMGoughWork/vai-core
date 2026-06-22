"""stdlib.todo.mark_blocked — Mark a todo item as blocked (Phase 12a.13)."""

from __future__ import annotations

import os
import sqlite3

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.capabilities.planner.todo_store import TodoStore
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class TodoMarkBlockedPrimitive(PrimitiveBase):
    """Mark a todo item as blocked, with an optional reason.

    Blocked items won't be returned by ``todo.get_next`` until they are
    unblocked (by resetting to ``pending`` via ``todo.mark_failed`` with
    retries remaining).
    """

    name = "stdlib.todo.mark_blocked"
    description = "Mark a todo item as blocked with an optional reason"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "db_path": {
                "type": "string",
                "description": "Path to the SQLite todo-plan database (defaults to <workspace>/todo_plan.db)",
            },
            "id": {"type": "string", "description": "The todo item ID to mark as blocked"},
            "reason": {"type": "string", "description": "Why this item is blocked (optional)"},
        },
        "required": ["id"],
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
        if "id" not in args:
            raise ValueError("args must contain 'id' key")
        if "db_path" not in args:
            raise ValueError("args must contain 'db_path' key")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        if "db_path" not in args:
            workspace = context.get("workspace_path", os.getcwd())
            args["db_path"] = os.path.join(workspace, "todo_plan.db")
        self.validate_args(args)
        db_path = args["db_path"]
        todo_id = args["id"]
        reason = args.get("reason", "")

        conn = None
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            store = TodoStore(conn)
            store.ensure_tables()

            store.mark_blocked(todo_id, reason)

            return PrimitiveResult(
                status="success",
                data={
                    "id": todo_id,
                    "status": "blocked",
                    "reason": reason,
                },
            )
        except sqlite3.Error as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"SQLiteError: {exc}",
            )
        finally:
            if conn:
                conn.close()

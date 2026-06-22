"""stdlib.todo.mark_failed — Mark a todo item as failed, with retry support (Phase 12a.13)."""

from __future__ import annotations

import os
import sqlite3

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.capabilities.planner.todo_store import TodoStore
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class TodoMarkFailedPrimitive(PrimitiveBase):
    """Mark a todo item as failed. If retries remain, the item stays ``pending``
    for retry. If retries are exhausted, the status is set to ``failed``.
    """

    name = "stdlib.todo.mark_failed"
    description = "Mark a todo item as failed (auto-retries if retries remain)"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "db_path": {
                "type": "string",
                "description": "Path to the SQLite todo-plan database (defaults to <workspace>/todo_plan.db)",
            },
            "id": {"type": "string", "description": "The todo item ID to mark as failed"},
            "error": {"type": "string", "description": "Error message describing what went wrong (optional)"},
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
        error_message = args.get("error", "")

        conn = None
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            store = TodoStore(conn)
            store.ensure_tables()

            # mark_failed returns True when retries remain (re-queued as pending)
            has_retries = store.mark_failed(todo_id, error_message)
            retries_exhausted = not has_retries

            # Re-read to get current state
            item = store.get(todo_id)
            current_status = item.status if item else "unknown"

            return PrimitiveResult(
                status="success",
                data={
                    "id": todo_id,
                    "status": current_status,
                    "retries_exhausted": retries_exhausted,
                    "message": (
                        "Retries exhausted — status set to 'failed'."
                        if retries_exhausted
                        else "Retry queued — status reset to 'pending'."
                    ),
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

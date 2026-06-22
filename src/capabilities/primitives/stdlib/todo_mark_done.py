"""stdlib.todo.mark_done — Mark a todo item as successfully completed (Phase 12a.13)."""

from __future__ import annotations

import sqlite3

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.capabilities.planner.todo_store import TodoStore
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class TodoMarkDonePrimitive(PrimitiveBase):
    """Mark a todo item as ``done`` after successful completion."""

    name = "stdlib.todo.mark_done"
    description = "Mark a todo item as successfully completed"
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
        if "id" not in args:
            raise ValueError("args must contain 'id' key")
        if "db_path" not in args:
            raise ValueError("args must contain 'db_path' key")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        db_path = args["db_path"]
        todo_id = args["id"]

        conn = None
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            store = TodoStore(conn)
            store.ensure_tables()

            # Verify the item exists before attempting to mark done
            existing = store.get(todo_id)
            if existing is None:
                return PrimitiveResult(
                    status="error",
                    data=None,
                    error=f"Todo '{todo_id}' does not exist",
                )

            store.mark_done(todo_id)

            is_complete = store.is_complete()
            status_counts = store.get_status_counts()

            return PrimitiveResult(
                status="success",
                data={
                    "id": todo_id,
                    "status": "done",
                    "is_complete": is_complete,
                    "status_counts": status_counts,
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

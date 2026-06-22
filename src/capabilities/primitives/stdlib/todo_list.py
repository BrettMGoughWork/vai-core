"""stdlib.todo.list — List all todo items with statuses and dependencies (Phase 12a.13)."""

from __future__ import annotations

import os
import sqlite3

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.capabilities.planner.todo_store import TodoStore
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class TodoListPrimitive(PrimitiveBase):
    """List all todo items with their current status, dependencies, and retries remaining."""

    name = "stdlib.todo.list"
    description = "List all todo items with statuses and dependencies"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "db_path": {
                "type": "string",
                "description": "Path to the SQLite todo-plan database (defaults to <workspace>/todo_plan.db)",
            },
        },
        "required": [],
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
        if "db_path" not in args:
            raise ValueError("args must contain 'db_path' key")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        if "db_path" not in args:
            workspace = context.get("workspace_path", os.getcwd())
            args["db_path"] = os.path.join(workspace, "todo_plan.db")
        self.validate_args(args)
        db_path = args["db_path"]

        conn = None
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            store = TodoStore(conn)
            store.ensure_tables()

            items = store.get_all()
            result_items = []
            for item in items:
                deps = store.get_deps(item.id)
                result_items.append({
                    "id": item.id,
                    "title": item.title,
                    "description": item.description,
                    "status": item.status,
                    "retries_remaining": item.retries_remaining,
                    "depends_on": deps,
                    "created_at": item.created_at,
                    "updated_at": item.updated_at,
                })

            counts = store.get_status_counts()
            is_complete = store.is_complete()

            return PrimitiveResult(
                status="success",
                data={
                    "items": result_items,
                    "total": len(result_items),
                    "status_counts": counts,
                    "is_complete": is_complete,
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

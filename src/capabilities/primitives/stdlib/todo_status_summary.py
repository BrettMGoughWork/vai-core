"""stdlib.todo.status_summary — Get a high-level summary of todo plan progress (Phase 12a.13)."""

from __future__ import annotations

import os
import sqlite3

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.capabilities.planner.todo_store import TodoStore
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class TodoStatusSummaryPrimitive(PrimitiveBase):
    """Get a high-level summary: counts by status, whether the plan is complete,
    and the next ready item if any remain.
    """

    name = "stdlib.todo.status_summary"
    description = "Get a high-level summary of todo list progress"
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

            counts = store.get_status_counts()
            is_complete = store.is_complete()
            total = store.total_count()
            done_count = store.done_count()
            has_work = store.has_work_remaining()

            blocked_items = []
            for item in store.get_all():
                if item.status == "blocked":
                    deps = store.get_deps(item.id)
                    blocked_items.append({"id": item.id, "title": item.title, "depends_on": deps})

            return PrimitiveResult(
                status="success",
                data={
                    "total": total,
                    "done": done_count,
                    "status_counts": counts,
                    "is_complete": is_complete,
                    "has_work_remaining": has_work,
                    "progress_pct": round(done_count / total * 100, 1) if total > 0 else 0,
                    "blocked_items": blocked_items,
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

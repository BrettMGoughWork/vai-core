"""stdlib.todo.get_next — Get the next pending, unblocked todo item (Phase 12a.13)."""

from __future__ import annotations

import sqlite3

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.capabilities.planner.todo_store import TodoStore
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class TodoGetNextPrimitive(PrimitiveBase):
    """Get the next pending item that has all dependencies satisfied.

    Returns the highest-priority (oldest) todo that is ready to work on.
    If all pending items are blocked by dependencies, returns ``next: null``.
    """

    name = "stdlib.todo.get_next"
    description = "Get the next pending todo that is ready to execute (dependencies satisfied)"
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
        if "db_path" not in args:
            raise ValueError("args must contain 'db_path' key")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        db_path = args["db_path"]

        conn = None
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            store = TodoStore(conn)
            store.ensure_tables()

            next_item = store.get_next_pending()

            if next_item is None:
                has_work = store.has_work_remaining()
                return PrimitiveResult(
                    status="success",
                    data={
                        "next": None,
                        "message": "No unblocked pending items. All items are either done, in progress, blocked, or failed.",
                        "has_work_remaining": has_work,
                    },
                )

            deps = store.get_deps(next_item.id)
            return PrimitiveResult(
                status="success",
                data={
                    "next": {
                        "id": next_item.id,
                        "title": next_item.title,
                        "description": next_item.description,
                        "status": next_item.status,
                        "depends_on": deps,
                    },
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

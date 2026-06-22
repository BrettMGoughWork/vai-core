"""stdlib.todo.create_batch — Create multiple todo items and their dependencies (Phase 12a.13)."""

from __future__ import annotations

import sqlite3

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.capabilities.planner.todo_store import TodoStore
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class TodoCreateBatchPrimitive(PrimitiveBase):
    """Create multiple todo items and wire up dependencies in one call.

    This is the primary entry point for populating a todo-list plan.
    Each item dict needs ``id``, ``title``, and optionally ``description``,
    ``retries_remaining``, and ``depends_on`` (list of todo ids).
    """

    name = "stdlib.todo.create_batch"
    description = "Create multiple todo items with dependencies in one batch"
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
        if "items" not in args:
            raise ValueError("args must contain 'items' key")
        items = args["items"]
        if not isinstance(items, list) or len(items) == 0:
            raise ValueError("'items' must be a non-empty list of dicts")
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"items[{i}] must be a dict, got {type(item).__name__}")
            if "id" not in item:
                raise ValueError(f"items[{i}] must contain 'id' key")
            if "title" not in item:
                raise ValueError(f"items[{i}] must contain 'title' key")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        db_path = args["db_path"]
        items = args["items"]

        conn = None
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            store = TodoStore(conn)
            store.ensure_tables()

            store.add_todos_batch(items)

            dep_count = 0
            for item in items:
                for dep_id in item.get("depends_on", []):
                    store.add_dep(item["id"], dep_id)
                    dep_count += 1

            return PrimitiveResult(
                status="success",
                data={
                    "created": len(items),
                    "dependencies_added": dep_count,
                    "ids": [it["id"] for it in items],
                },
            )
        except sqlite3.IntegrityError as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"IntegrityError: {exc}",
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

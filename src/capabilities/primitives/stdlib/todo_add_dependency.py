"""stdlib.todo.add_dependency — Add a dependency between two todo items (Phase 12a.13)."""

from __future__ import annotations

import sqlite3

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.capabilities.planner.todo_store import TodoStore
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class TodoAddDependencyPrimitive(PrimitiveBase):
    """Declare that one todo item depends on another.

    The dependent item won't be returned by ``todo.get_next`` until its
    dependency is ``done``.
    """

    name = "stdlib.todo.add_dependency"
    description = "Add a dependency: one todo must complete before another can start"
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
        if "todo_id" not in args:
            raise ValueError("args must contain 'todo_id' key")
        if "depends_on" not in args:
            raise ValueError("args must contain 'depends_on' key")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        db_path = args["db_path"]
        todo_id = args["todo_id"]
        depends_on = args["depends_on"]

        conn = None
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            store = TodoStore(conn)
            store.ensure_tables()

            store.add_dep(todo_id, depends_on)
            all_deps = store.get_deps(todo_id)

            return PrimitiveResult(
                status="success",
                data={
                    "todo_id": todo_id,
                    "depends_on": depends_on,
                    "all_dependencies": all_deps,
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

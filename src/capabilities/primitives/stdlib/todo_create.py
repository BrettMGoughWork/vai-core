"""stdlib.todo.create — Create a single todo item in a todo-list plan (Phase 12a.13)."""

from __future__ import annotations

import os
import sqlite3

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.capabilities.planner.todo_store import TodoStore
from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class TodoCreatePrimitive(PrimitiveBase):
    """Create a single todo item with a unique kebab-case ID."""

    name = "stdlib.todo.create"
    description = "Create a single todo item in the plan"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "db_path": {
                "type": "string",
                "description": "Path to the SQLite todo-plan database (defaults to <workspace>/todo_plan.db)",
            },
            "id": {"type": "string", "description": "Unique kebab-case identifier for the todo"},
            "title": {"type": "string", "description": "Short gerund-form title describing the work"},
            "description": {"type": "string", "description": "Detailed description of what needs to be done"},
            "retries_remaining": {"type": "integer", "description": "Number of retry attempts allowed (default 3)"},
        },
        "required": ["id", "title"],
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
        for key in ("id", "title", "db_path"):
            if key not in args:
                raise ValueError(f"args must contain '{key}' key")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        if "db_path" not in args:
            workspace = context.get("workspace_path", os.getcwd())
            args["db_path"] = os.path.join(workspace, "todo_plan.db")
        self.validate_args(args)
        db_path = args["db_path"]
        todo_id = args["id"]
        title = args["title"]
        description = args.get("description", "")
        retries_remaining = args.get("retries_remaining", 3)

        conn = None
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            store = TodoStore(conn)
            store.ensure_tables()
            store.add_todo(
                todo_id=todo_id,
                title=title,
                description=description,
                retries_remaining=retries_remaining,
            )
            return PrimitiveResult(
                status="success",
                data={"id": todo_id, "title": title, "status": "pending"},
            )
        except sqlite3.IntegrityError:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"Todo '{todo_id}' already exists. Use a unique ID.",
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

"""stdlib.file.exists — Check if a file or directory exists (Phase 3.18.1)."""

from __future__ import annotations

import json
import os

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class FileExistsPrimitive(PrimitiveBase):
    """Check whether a file or directory exists at the given path."""

    name = "stdlib.file.exists"
    description = "Check if a file or directory exists at the given path"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to check for existence"},
        },
        "required": ["path"],
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
        if "path" not in args:
            raise ValueError("args must contain 'path' key")
        path = args["path"]
        if not isinstance(path, str):
            raise ValueError(f"'path' must be a string, got {type(path).__name__}")
        if "\x00" in path:
            raise ValueError("'path' must not contain null bytes")
        if not path:
            raise ValueError("'path' must not be empty")
        try:
            json.dumps(path)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"'path' must be JSON-serializable: {exc}") from exc

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        path = args["path"]
        try:
            exists = os.path.exists(path)
        except OSError as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"OSError: {exc}",
            )
        return PrimitiveResult(status="success", data={"exists": exists})

"""stdlib.file.append — Append UTF-8 string content to a file (Phase 3.18.1)."""

from __future__ import annotations

import json
import os

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class FileAppendPrimitive(PrimitiveBase):
    """Append a UTF-8 string to an existing file."""

    name = "stdlib.file.append"
    description = "Append UTF-8 string content to a file"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the file to append to"},
            "content": {"type": "string", "description": "UTF-8 string content to append to the file"},
        },
        "required": ["path", "content"],
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
        for key in ("path", "content"):
            if key not in args:
                raise ValueError(f"args must contain '{key}' key")
            value = args[key]
            if not isinstance(value, str):
                raise ValueError(
                    f"'{key}' must be a string, got {type(value).__name__}"
                )
            try:
                json.dumps(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"'{key}' must be JSON-serializable: {exc}"
                ) from exc
        if "\x00" in args["path"]:
            raise ValueError("'path' must not contain null bytes")
        if not args["path"]:
            raise ValueError("'path' must not be empty")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        try:
            with open(args["path"], "a", encoding="utf-8") as f:
                f.write(args["content"])
        except FileNotFoundError as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"FileNotFoundError: {exc}",
            )
        except PermissionError as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"PermissionError: {exc}",
            )
        except OSError as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"OSError: {exc}",
            )
        return PrimitiveResult(status="success", data={"ok": True})

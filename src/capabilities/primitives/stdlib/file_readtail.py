"""stdlib.file.readtail — Read last N lines of a file (Phase 3.18.1)."""

from __future__ import annotations

import json
import os

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class FileReadtailPrimitive(PrimitiveBase):
    """Read the last N lines from a file and return them as a UTF-8 string."""

    name = "stdlib.file.readtail"
    description = "Read last N lines of a file as UTF-8 string"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the file to read"},
            "lines": {"type": "integer", "description": "Number of lines to read from the end of the file", "minimum": 1},
        },
        "required": ["path", "lines"],
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
        if "lines" not in args:
            raise ValueError("args must contain 'lines' key")
        lines = args["lines"]
        if not isinstance(lines, int):
            raise ValueError(f"'lines' must be an integer, got {type(lines).__name__}")
        if lines <= 0:
            raise ValueError(f"'lines' must be positive, got {lines}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        path = args["path"]
        n_lines = args["lines"]
        try:
            with open(path, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
            tail = all_lines[-n_lines:] if n_lines <= len(all_lines) else all_lines
            content = "".join(tail)
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
        except UnicodeDecodeError as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"UnicodeDecodeError: {exc}",
            )
        except OSError as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"OSError: {exc}",
            )
        return PrimitiveResult(status="success", data={"content": content})

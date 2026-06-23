"""stdlib.file.readrange — Read byte range from a file (Phase 3.18.1)."""

from __future__ import annotations

import json
import os

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class FileReadrangePrimitive(PrimitiveBase):
    """Read a byte range from a file and return it as a UTF-8 string."""

    name = "stdlib.file.readrange"
    description = "Read byte range from a file as UTF-8 string"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the file to read from"},
            "start": {"type": "integer", "description": "Starting byte offset (0-indexed, inclusive)", "minimum": 0},
            "end": {"type": "integer", "description": "Ending byte offset (exclusive, must be greater than start)"},
        },
        "required": ["path", "start", "end"],
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
        for key in ("start", "end"):
            if key not in args:
                raise ValueError(f"args must contain '{key}' key")
            value = args[key]
            if not isinstance(value, int):
                raise ValueError(f"'{key}' must be an integer, got {type(value).__name__}")
        start = args["start"]
        end = args["end"]
        if start < 0:
            raise ValueError(f"'start' must be >= 0, got {start}")
        if end <= start:
            raise ValueError(f"'end' ({end}) must be greater than 'start' ({start})")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        path = args["path"]
        start = args["start"]
        end = args["end"]
        try:
            with open(path, "rb") as f:
                f.seek(start)
                data = f.read(end - start)
            content = data.decode("utf-8")
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

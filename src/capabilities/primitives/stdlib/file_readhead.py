"""stdlib.file.readhead — Read first N lines of a file (Phase 3.18.1)."""

from __future__ import annotations

import json
import os

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


class FileReadheadPrimitive(PrimitiveBase):
    """Read the first N lines from a file and return them as a UTF-8 string."""

    name = "stdlib.file.readhead"
    description = "Read first N lines of a file as UTF-8 string"
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
                lines = []
                for _ in range(n_lines):
                    line = f.readline()
                    if not line:
                        break
                    lines.append(line)
                content = "".join(lines)
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

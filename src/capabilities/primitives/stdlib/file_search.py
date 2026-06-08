"""stdlib.file.search — Search a file for lines matching a regex (Phase 3.18.1)."""

from __future__ import annotations

import json
import os
import re

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


class FileSearchPrimitive(PrimitiveBase):
    """Search a file line by line for matches against a regex pattern."""

    name = "stdlib.file.search"
    description = "Search a file for lines matching a regex pattern"
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
        if "pattern" not in args:
            raise ValueError("args must contain 'pattern' key")
        pattern = args["pattern"]
        if not isinstance(pattern, str):
            raise ValueError(f"'pattern' must be a string, got {type(pattern).__name__}")
        if not pattern:
            raise ValueError("'pattern' must not be empty")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        path = args["path"]
        pattern = args["pattern"]
        try:
            regex = re.compile(pattern)
            matches: list[str] = []
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if regex.search(line):
                        matches.append(line.rstrip("\n").rstrip("\r"))
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
        except re.error as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"re.error: {exc}",
            )
        except OSError as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"OSError: {exc}",
            )
        except UnicodeDecodeError as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"UnicodeDecodeError: {exc}",
            )
        return PrimitiveResult(status="success", data={"matches": matches})

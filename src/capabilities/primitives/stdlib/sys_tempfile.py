"""stdlib.sys.tempfile — Create a temporary file and return its path (Phase 3.18.8)."""

from __future__ import annotations

import os
import tempfile
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class SysTempFilePrimitive(PrimitiveBase):
    """Create a temporary file and return its absolute path."""

    name = "stdlib.sys.tempfile"
    description = "Create a temporary file and return its path"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "suffix": {
                "type": "string",
                "description": "File suffix/extension (e.g. '.txt', '.json')",
            },
            "prefix": {
                "type": "string",
                "description": "Filename prefix (default: 'vai_')",
            },
            "directory": {
                "type": "string",
                "description": "Directory to create the file in (default: system temp dir)",
            },
            "content": {
                "type": "string",
                "description": "Initial text content to write to the temp file",
            },
        },
        "required": [],
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
        suffix = args.get("suffix")
        if suffix is not None and not isinstance(suffix, str):
            raise ValueError(f"args['suffix'] must be a string, got {type(suffix).__name__}")
        prefix = args.get("prefix")
        if prefix is not None and not isinstance(prefix, str):
            raise ValueError(f"args['prefix'] must be a string, got {type(prefix).__name__}")
        directory = args.get("directory")
        if directory is not None and not isinstance(directory, str):
            raise ValueError(f"args['directory'] must be a string, got {type(directory).__name__}")
        content = args.get("content")
        if content is not None and not isinstance(content, str):
            raise ValueError(f"args['content'] must be a string, got {type(content).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        suffix = args.get("suffix", "")
        prefix = args.get("prefix", "vai_")
        directory = args.get("directory")
        content = args.get("content")

        try:
            fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=directory, text=True)
            if content is not None:
                os.write(fd, content.encode("utf-8"))
            os.close(fd)
        except Exception as exc:
            return PrimitiveResult(status="error", error=str(exc))

        return PrimitiveResult(
            status="success",
            data={
                "path": os.path.abspath(path),
                "exists": os.path.exists(path),
                "size_bytes": os.path.getsize(path),
            },
        )

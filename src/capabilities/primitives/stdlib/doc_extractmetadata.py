"""stdlib.doc.extractmetadata — Extract metadata from a file (Phase 3.18.7)."""

from __future__ import annotations

import os
import stat
import time
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class DocExtractMetadataPrimitive(PrimitiveBase):
    """Extract file metadata: size, timestamps, permissions, and type info."""

    name = "stdlib.doc.extractmetadata"
    description = "Extract file metadata (size, timestamps, permissions)"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to extract metadata from",
            },
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
        if not isinstance(args["path"], str):
            raise ValueError(f"args['path'] must be a string, got {type(args['path']).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        path = args["path"]

        if not os.path.exists(path):
            return PrimitiveResult(
                status="error",
                error=f"File not found: {path}",
            )

        st = os.stat(path)
        metadata = {
            "path": os.path.abspath(path),
            "filename": os.path.basename(path),
            "size_bytes": st.st_size,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_ctime)),
            "modified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
            "accessed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_atime)),
            "is_file": bool(stat.S_ISREG(st.st_mode)),
            "is_directory": bool(stat.S_ISDIR(st.st_mode)),
            "permissions": oct(stat.S_IMODE(st.st_mode)),
            "extension": os.path.splitext(path)[1].lower(),
        }

        return PrimitiveResult(
            status="success",
            data=metadata,
        )

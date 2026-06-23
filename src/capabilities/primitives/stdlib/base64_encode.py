"""stdlib.base64.encode — Base64 encode data (Phase 3.18.10)."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class Base64EncodePrimitive(PrimitiveBase):
    """Encode a string or file content to base64."""

    name = "stdlib.base64.encode"
    description = "Base64 encode a string or file"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "data": {
                "type": "string",
                "description": "Text content to base64-encode",
            },
            "file": {
                "type": "string",
                "description": "Path to a file whose bytes will be base64-encoded",
            },
        },
        "anyOf": [{"required": ["data"]}, {"required": ["file"]}],
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
        has_data = "data" in args
        has_file = "file" in args
        if not has_data and not has_file:
            raise ValueError("args must contain 'data' or 'file' key")
        if has_file and not isinstance(args["file"], str):
            raise ValueError(f"args['file'] must be a string, got {type(args['file']).__name__}")
        if has_data and not isinstance(args["data"], str):
            raise ValueError(f"args['data'] must be a string, got {type(args['data']).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)

        try:
            if "file" in args:
                file_path = Path(args["file"])
                if not file_path.exists():
                    return PrimitiveResult(status="error", error=f"File not found: {file_path}")
                content = file_path.read_bytes()
                data = base64.b64encode(content).decode("ascii")
                return PrimitiveResult(
                    status="success",
                    data={
                        "encoded": data,
                        "original_size": len(content),
                        "encoded_size": len(data),
                    },
                )
            else:
                content = args["data"].encode("utf-8")
                data = base64.b64encode(content).decode("ascii")
                return PrimitiveResult(
                    status="success",
                    data={
                        "encoded": data,
                        "original_size": len(content),
                        "encoded_size": len(data),
                    },
                )
        except Exception as e:
            return PrimitiveResult(
                status="error",
                error=f"Base64 encoding failed: {e}",
            )

"""stdlib.base64.decode — Base64 decode data (Phase 3.18.10)."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class Base64DecodePrimitive(PrimitiveBase):
    """Decode base64-encoded data back to original form."""

    name = "stdlib.base64.decode"
    description = "Base64 decode a string to its original content"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "data": {
                "type": "string",
                "description": "Base64-encoded string to decode",
            },
        },
        "required": ["data"],
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
        if "data" not in args:
            raise ValueError("args must contain 'data' key")
        if not isinstance(args["data"], str):
            raise ValueError(f"args['data'] must be a string, got {type(args['data']).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)

        try:
            decoded_bytes = base64.b64decode(args["data"], validate=True)
            text = decoded_bytes.decode("utf-8", errors="replace")
            return PrimitiveResult(
                status="success",
                data={
                    "text": text,
                    "decoded_size": len(decoded_bytes),
                },
            )
        except Exception as e:
            return PrimitiveResult(
                status="error",
                error=f"Base64 decoding failed: {e}",
            )

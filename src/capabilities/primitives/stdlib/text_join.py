"""stdlib.text.join — Join a list of strings with a delimiter (Phase 3.18.7)."""

from __future__ import annotations

from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


class TextJoinPrimitive(PrimitiveBase):
    """Join a list of strings into a single string using a delimiter."""

    name = "stdlib.text.join"
    description = "Join a list of strings with a delimiter"
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
        if "parts" not in args:
            raise ValueError("args must contain 'parts' key")
        if not isinstance(args["parts"], list):
            raise ValueError(f"args['parts'] must be a list, got {type(args['parts']).__name__}")
        if not all(isinstance(p, str) for p in args["parts"]):
            raise ValueError("args['parts'] must be a list of strings")
        delimiter = args.get("delimiter", "")
        if not isinstance(delimiter, str):
            raise ValueError(f"args['delimiter'] must be a string, got {type(delimiter).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        parts = args["parts"]
        delimiter = args.get("delimiter", "")
        result_text = delimiter.join(parts)
        return PrimitiveResult(
            status="success",
            data={"text": result_text, "length": len(result_text)},
        )

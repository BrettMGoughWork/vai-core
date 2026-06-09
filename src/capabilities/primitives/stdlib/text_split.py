"""stdlib.text.split — Split a string by a delimiter (Phase 3.18.7)."""

from __future__ import annotations

from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


class TextSplitPrimitive(PrimitiveBase):
    """Split a string into a list of substrings by a delimiter."""

    name = "stdlib.text.split"
    description = "Split a string into a list by a delimiter"
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
        if "text" not in args:
            raise ValueError("args must contain 'text' key")
        if not isinstance(args["text"], str):
            raise ValueError(f"args['text'] must be a string, got {type(args['text']).__name__}")
        delimiter = args.get("delimiter", " ")
        if not isinstance(delimiter, str):
            raise ValueError(f"args['delimiter'] must be a string, got {type(delimiter).__name__}")
        maxsplit = args.get("maxsplit")
        if maxsplit is not None and not isinstance(maxsplit, int):
            raise ValueError(f"args['maxsplit'] must be an integer, got {type(maxsplit).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        text = args["text"]
        delimiter = args.get("delimiter", " ")
        maxsplit = args.get("maxsplit", -1)
        parts = text.split(delimiter, maxsplit)
        return PrimitiveResult(
            status="success",
            data={"parts": parts, "count": len(parts)},
        )

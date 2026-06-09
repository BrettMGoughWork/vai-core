"""stdlib.text.extract — Extract substrings using regex patterns (Phase 3.18.7)."""

from __future__ import annotations

import re
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


class TextExtractPrimitive(PrimitiveBase):
    """Extract substrings from text using a regex pattern."""

    name = "stdlib.text.extract"
    description = "Extract substrings from text using a regex pattern"
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
        if "pattern" not in args:
            raise ValueError("args must contain 'pattern' key")
        if not isinstance(args["pattern"], str):
            raise ValueError(f"args['pattern'] must be a string, got {type(args['pattern']).__name__}")
        try:
            re.compile(args["pattern"])
        except re.error as exc:
            raise ValueError(f"args['pattern'] is not a valid regex: {exc}")
        flags = args.get("flags", 0)
        if not isinstance(flags, int):
            raise ValueError(f"args['flags'] must be an integer, got {type(flags).__name__}")
        group = args.get("group")
        if group is not None and not isinstance(group, (int, str)):
            raise ValueError(f"args['group'] must be an int or str, got {type(group).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        text = args["text"]
        pattern = args["pattern"]
        flags = args.get("flags", 0)
        group = args.get("group")

        matches = re.findall(pattern, text, flags=flags)
        if group is not None:
            # Return only the specified group from full matches
            compiled = re.compile(pattern, flags)
            matches = [m.group(group) if isinstance(group, int) else m.group(group)
                       for m in compiled.finditer(text)]

        return PrimitiveResult(
            status="success",
            data={"matches": matches, "count": len(matches)},
        )

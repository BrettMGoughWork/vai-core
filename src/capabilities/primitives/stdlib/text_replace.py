"""stdlib.text.replace — Replace substrings in text (Phase 3.18.7)."""

from __future__ import annotations

from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class TextReplacePrimitive(PrimitiveBase):
    """Replace occurrences of a substring within a string."""

    name = "stdlib.text.replace"
    description = "Replace substrings in text"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The source text to perform replacements on",
            },
            "old": {
                "type": "string",
                "description": "Substring to search for and replace",
            },
            "new": {
                "type": "string",
                "description": "Replacement string",
            },
            "count": {
                "type": "integer",
                "description": "Maximum number of replacements (default: replace all)",
            },
        },
        "required": ["text", "old", "new"],
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
        if "text" not in args:
            raise ValueError("args must contain 'text' key")
        if not isinstance(args["text"], str):
            raise ValueError(f"args['text'] must be a string, got {type(args['text']).__name__}")
        if "old" not in args:
            raise ValueError("args must contain 'old' key")
        if not isinstance(args["old"], str):
            raise ValueError(f"args['old'] must be a string, got {type(args['old']).__name__}")
        if "new" not in args:
            raise ValueError("args must contain 'new' key")
        if not isinstance(args["new"], str):
            raise ValueError(f"args['new'] must be a string, got {type(args['new']).__name__}")
        count = args.get("count")
        if count is not None and not isinstance(count, int):
            raise ValueError(f"args['count'] must be an integer, got {type(count).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        text = args["text"]
        old = args["old"]
        new = args["new"]
        count = args.get("count", -1)
        result_text = text.replace(old, new, count)
        return PrimitiveResult(
            status="success",
            data={
                "text": result_text,
                "replaced": 1 if old in text and old != new and old != "" else 0,
            },
        )

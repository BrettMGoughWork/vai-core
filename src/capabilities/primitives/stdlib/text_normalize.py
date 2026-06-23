"""stdlib.text.normalize — Normalize whitespace and casing in text (Phase 3.18.7)."""

from __future__ import annotations

import re
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class TextNormalizePrimitive(PrimitiveBase):
    """Normalize text by trimming, collapsing whitespace, and optionally lowering case."""

    name = "stdlib.text.normalize"
    description = "Normalize whitespace and casing in text"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to normalize",
            },
            "lowercase": {
                "type": "boolean",
                "description": "Convert text to lowercase (default: false)",
            },
            "strip_punctuation": {
                "type": "boolean",
                "description": "Remove punctuation characters (default: false)",
            },
        },
        "required": ["text"],
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
        lowercase = args.get("lowercase", False)
        if not isinstance(lowercase, bool):
            raise ValueError(f"args['lowercase'] must be a bool, got {type(lowercase).__name__}")
        strip_punctuation = args.get("strip_punctuation", False)
        if not isinstance(strip_punctuation, bool):
            raise ValueError(f"args['strip_punctuation'] must be a bool, got {type(strip_punctuation).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        text = args["text"]
        lowercase = args.get("lowercase", False)
        strip_punctuation = args.get("strip_punctuation", False)

        # Collapse all whitespace to single spaces and trim
        text = re.sub(r"\s+", " ", text).strip()

        if lowercase:
            text = text.lower()

        if strip_punctuation:
            text = re.sub(r"[^\w\s]", "", text)

        return PrimitiveResult(
            status="success",
            data={"text": text, "length": len(text)},
        )

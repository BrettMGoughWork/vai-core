"""stdlib.toml.parse — Parse a TOML string into a Python object (Phase 3.18.2)."""

from __future__ import annotations

import tomllib

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


class TomlParsePrimitive(PrimitiveBase):
    """Parse a TOML string into a Python object."""

    name = "stdlib.toml.parse"
    description = "Parse a TOML string into a Python object"
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
        text = args["text"]
        if not isinstance(text, str):
            raise ValueError(f"'text' must be a string, got {type(text).__name__}")
        if not text:
            raise ValueError("'text' must not be empty")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        text = args["text"]
        try:
            parsed = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"tomllib.TOMLDecodeError: {exc}",
            )
        return PrimitiveResult(status="success", data={"value": parsed})

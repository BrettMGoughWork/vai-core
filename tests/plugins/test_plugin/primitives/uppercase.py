"""Test primitive: uppercase transformer."""

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


class UppercasePrimitive(PrimitiveBase):
    """Return the input text converted to uppercase."""

    name = "plugin.test-plugin.uppercase"
    description = "Convert text to uppercase"
    primitive_type = PrimitiveType.PYTHON

    def validate_args(self, args: dict) -> None:
        if "text" not in args:
            raise ValueError("args must contain 'text' key")
        if not isinstance(args["text"], str):
            raise ValueError(f"'text' must be a string, got {type(args['text']).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        return PrimitiveResult(
            status="success",
            data={"value": args["text"].upper()},
        )

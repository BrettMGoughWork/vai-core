"""Test primitive: echo B."""
from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


class EchoBPrimitive(PrimitiveBase):
    """Echo B primitive."""
    name = "echo_b"
    description = "Echo B primitive"
    primitive_type = PrimitiveType.PYTHON

    def validate_args(self, args: dict) -> None:
        pass

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        return PrimitiveResult(status="success", data={"value": "echo_b"})

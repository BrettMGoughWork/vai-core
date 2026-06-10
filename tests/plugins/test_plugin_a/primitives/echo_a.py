"""Test primitive: echo A."""
from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


class EchoAPrimitive(PrimitiveBase):
    """Echo A primitive."""
    name = "echo_a"
    description = "Echo A primitive"
    primitive_type = PrimitiveType.PYTHON

    def validate_args(self, args: dict) -> None:
        pass

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        return PrimitiveResult(status="success", data={"value": "echo_a"})

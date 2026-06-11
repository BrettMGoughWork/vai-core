"""stdlib.json.get — Get a key from a JSON object (Phase 3.18.2)."""

from __future__ import annotations

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class JsonGetPrimitive(PrimitiveBase):
    """Get a key from a JSON object."""

    name = "stdlib.json.get"
    description = "Get a key from a JSON object"
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
        if "obj" not in args:
            raise ValueError("args must contain 'obj' key")
        obj = args["obj"]
        if not isinstance(obj, dict):
            raise ValueError(f"'obj' must be a dict, got {type(obj).__name__}")
        if "key" not in args:
            raise ValueError("args must contain 'key' key")
        key = args["key"]
        if not isinstance(key, str):
            raise ValueError(f"'key' must be a string, got {type(key).__name__}")
        if not key:
            raise ValueError("'key' must not be empty")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        obj = args["obj"]
        key = args["key"]
        try:
            result = obj[key]
        except KeyError as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"KeyError: {exc}",
            )
        except TypeError as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"TypeError: {exc}",
            )
        return PrimitiveResult(status="success", data={"value": result})

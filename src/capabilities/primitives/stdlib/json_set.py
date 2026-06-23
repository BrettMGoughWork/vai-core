"""stdlib.json.set — Set a key on a JSON object, returning the modified object (Phase 3.18.2)."""

from __future__ import annotations

import copy
import json

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class JsonSetPrimitive(PrimitiveBase):
    """Set a key on a JSON object, returning the modified object."""

    name = "stdlib.json.set"
    description = "Set a key on a JSON object, returning the modified object"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "obj": {
                "type": "object",
                "description": "The JSON object (dict) to modify",
            },
            "key": {
                "type": "string",
                "description": "The key to set",
            },
            "value": {
                "description": "The value to assign (any JSON-serializable type)",
            },
        },
        "required": ["obj", "key", "value"],
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
        # value is validated as JSON-serializable in execute to avoid double-serializing

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        obj = args["obj"]
        key = args["key"]
        value = args["value"]

        try:
            json.dumps(value)
        except (TypeError, ValueError) as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"TypeError: value is not JSON-serializable: {exc}",
            )

        modified = copy.deepcopy(obj)
        modified[key] = value
        return PrimitiveResult(status="success", data={"obj": modified})

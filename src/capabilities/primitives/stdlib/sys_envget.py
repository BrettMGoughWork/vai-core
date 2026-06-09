"""stdlib.sys.envget — Get an environment variable value (Phase 3.18.8)."""

from __future__ import annotations

import os
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


class SysEnvGetPrimitive(PrimitiveBase):
    """Get the value of an environment variable."""

    name = "stdlib.sys.envget"
    description = "Get an environment variable value"
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
        if "key" not in args:
            raise ValueError("args must contain 'key' key")
        if not isinstance(args["key"], str):
            raise ValueError(f"args['key'] must be a string, got {type(args['key']).__name__}")
        if args["key"] == "":
            raise ValueError("args['key'] must not be empty")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        key = args["key"]
        default = args.get("default")
        value = os.environ.get(key, default)
        return PrimitiveResult(
            status="success",
            data={
                "key": key,
                "value": value,
                "found": value is not None,
            },
        )

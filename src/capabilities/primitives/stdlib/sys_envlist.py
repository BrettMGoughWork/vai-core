"""stdlib.sys.envlist — List all environment variables (Phase 3.18.8)."""

from __future__ import annotations

import os
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class SysEnvListPrimitive(PrimitiveBase):
    """List all environment variables, optionally filtered by prefix."""

    name = "stdlib.sys.envlist"
    description = "List all environment variables"
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
        prefix = args.get("prefix")
        if prefix is not None and not isinstance(prefix, str):
            raise ValueError(f"args['prefix'] must be a string, got {type(prefix).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        prefix = args.get("prefix")
        env_vars = dict(os.environ)
        if prefix is not None:
            env_vars = {k: v for k, v in env_vars.items() if k.startswith(prefix)}
        return PrimitiveResult(
            status="success",
            data={"variables": env_vars, "count": len(env_vars)},
        )

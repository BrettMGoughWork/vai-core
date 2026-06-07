"""stdlib.echo — Return input unchanged (Phase 3.7.1)."""

from __future__ import annotations

import copy
import json
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


class EchoPrimitive(PrimitiveBase):
    """Return the input value unchanged — a pure, deterministic identity primitive."""

    name = "stdlib.echo"
    description = "Return input unchanged"
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
        if "value" not in args:
            raise ValueError("args must contain 'value' key")
        try:
            json.dumps(args["value"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"args['value'] must be JSON-serializable: {exc}"
            ) from exc

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        return PrimitiveResult(
            status="success", data={"value": copy.deepcopy(args["value"])}
        )

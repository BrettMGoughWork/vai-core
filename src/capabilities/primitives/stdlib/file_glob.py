"""stdlib.file.glob — Find files matching a glob pattern (Phase 3.18.1)."""

from __future__ import annotations

import glob

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.strategy.types.validation import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class FileGlobPrimitive(PrimitiveBase):
    """Find all files matching the given glob pattern (recursive)."""

    name = "stdlib.file.glob"
    description = "Find files matching a glob pattern"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern to match (e.g. '**/*.py', 'src/**/*.ts'). Supports recursive matching with **."},
        },
        "required": ["pattern"],
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
        if "pattern" not in args:
            raise ValueError("args must contain 'pattern' key")
        pattern = args["pattern"]
        if not isinstance(pattern, str):
            raise ValueError(f"'pattern' must be a string, got {type(pattern).__name__}")
        if not pattern:
            raise ValueError("'pattern' must not be empty")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        pattern = args["pattern"]
        try:
            paths = glob.glob(pattern, recursive=True)
        except ValueError as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"ValueError: {exc}",
            )
        return PrimitiveResult(status="success", data={"paths": paths})

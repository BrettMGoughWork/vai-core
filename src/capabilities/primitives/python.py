"""
PythonPrimitive — a primitive backed by a Python callable (Phase 3.1.3).

Python primitives run in-process and are the simplest, fastest
primitive type.  They are suitable for pure functions, data transforms,
and anything that doesn't need sandboxing.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveType, PrimitiveResult
from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class PythonPrimitive(PrimitiveBase):
    """A primitive backed by a Python callable."""

    __match_args__ = ("name",)
    input_schema = {
        "type": "object",
        "properties": {},
        "description": "Accepts arguments matching the wrapped callable's signature.",
    }

    def __init__(self, *, name: str, description: str, func: Callable[..., Any]) -> None:
        super().__init__(
            name=name,
            description=description,
            primitive_type=PrimitiveType.PYTHON,
        )
        self.func = func
        """The underlying Python callable that this primitive wraps."""
        self._sig = inspect.signature(func)

    # ------------------------------------------------------------------
    # PrimitiveBase interface
    # ------------------------------------------------------------------

    def validate_args(self, args: dict) -> None:
        """
        Validate that ``args`` matches the wrapped callable's signature.

        Every required parameter must be present and no unexpected keys
        may appear in ``args``.

        When the callable has a single positional parameter (the most
        common case) it receives the ``args`` dict directly and any keys
        are accepted — the callable is responsible for its own internal
        validation.  When the callable exposes multiple named parameters
        the ``execute`` method unpacks ``**args`` and this validator
        enforces parameter-name discipline.
        """
        if not isinstance(args, dict):
            raise ValueError("args must be a dict")

        params = list(self._sig.parameters.values())

        # Single-parameter callable — accept any keys
        if len(params) == 1:
            return

        # Multi-parameter callable — validate key discipline
        given = set(args)
        allowed = {p.name for p in params}
        unexpected = given - allowed
        if unexpected:
            raise ValueError(
                f"Unexpected arguments: {sorted(unexpected)}. "
                f"Expected: {sorted(allowed) or '(none)'}"
            )
        for p in params:
            if p.name not in given and p.default is p.empty:
                raise ValueError(f"Missing required argument: {p.name!r}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        """Execute the wrapped callable and wrap the outcome."""
        self.validate_args(args)

        try:
            if len(list(self._sig.parameters.values())) == 1:
                result = self.func(args)
            else:
                result = self.func(**args)
        except Exception as exc:
            return PrimitiveResult(
                status="error",
                error=str(exc),
            )

        return PrimitiveResult(
            status="success",
            data=result,
        )

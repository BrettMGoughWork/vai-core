"""
PythonPrimitive – a primitive implemented as a Python callable.

Python primitives run in-process and are the simplest, fastest
primitive type. They are suitable for pure functions, data transforms,
and anything that doesn't need sandboxing.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from src.capabilities.primitives.base import PrimitiveBase, PrimitiveType


class PythonPrimitive(PrimitiveBase):
    """A primitive backed by a Python callable."""

    def __init__(
        self,
        name: str,
        description: str,
        handler: Callable[..., Any],
        *,
        input_schema: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        side_effects: Optional[list[str]] = None,
        deterministic: bool = True,
        pure: bool = True,
        idempotent: bool = True,
        enabled: bool = True,
    ):
        super().__init__(
            name=name,
            primitive_type=PrimitiveType.PYTHON,
            description=description,
            handler=handler,
            input_schema=input_schema or {},
            output_schema=output_schema,
            side_effects=side_effects or [],
            deterministic=deterministic,
            pure=pure,
            idempotent=idempotent,
            enabled=enabled,
        )

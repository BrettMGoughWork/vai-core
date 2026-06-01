from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.core.types.validation import validate_structural

@dataclass
class ShapeValidationResult:
    ok: bool
    message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

def validate_execution_shape(
    expected_schema: Optional[Dict[str, Any]],
    actual_output: Any,
) -> ShapeValidationResult:
    """
    2.6.1 — Execution shape validator (expected vs actual).

    If no expected_schema is provided, we treat the shape as valid
    (S2 has nothing to compare against).
    """
    if expected_schema is None:
        return ShapeValidationResult(ok=True)

    # We rely on the existing structural validator to do the heavy lifting.
    try:
        validate_structural(expected_schema, actual_output)
        return ShapeValidationResult(ok=True)
    except Exception as exc:
        # We keep this intentionally generic; S2 will interpret the message.
        return ShapeValidationResult(
            ok=False,
            message=str(exc),
            details={
                "expected_schema": expected_schema,
                "actual_type": type(actual_output).__name__,
            },
        )
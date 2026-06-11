"""
Lightweight behavioural-anomaly detection for the S1 executor boundary.

Runs alongside execution-shape validation to catch unexpected patterns
that type-level checks would miss — for example, an output that is
structurally valid but semantically suspicious.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.strategy.planning.validation.execution_shape_validation import (
    ShapeValidationResult,
    validate_execution_shape,
)


def detect_behavioural_anomaly(
    expected_schema: Optional[Dict[str, Any]],
    actual_output: Any,
) -> Optional[str]:
    """
    Detect a behavioural anomaly in *actual_output* relative to
    *expected_schema*.

    Delegates to ``validate_execution_shape`` for structural validation
    and then applies additional heuristics:

    * Output produced without a declared schema is flagged as anomalous.
    * A dict-output where every declared field is ``None`` is flagged.
    * Further heuristics can be added here without changing the shape
      validation contract.

    Returns ``None`` when output appears normal, or a short
    human-readable description of the suspected anomaly.
    """
    if expected_schema is None:
        if actual_output is not None:
            return "Output produced with no declared schema"
        return None

    # Delegate to shape validation first
    result: ShapeValidationResult = validate_execution_shape(
        expected_schema, actual_output,
    )
    if not result.ok:
        return result.message

    # Heuristic: all-null dict fields
    expected_type = expected_schema.get("type", "").lower()
    if expected_type in ("object", "dict") and isinstance(actual_output, dict):
        properties = expected_schema.get("properties", {})
        if properties and actual_output:
            non_null = sum(1 for f in properties if actual_output.get(f) is not None)
            if non_null == 0:
                return "All declared fields are null"

    return None

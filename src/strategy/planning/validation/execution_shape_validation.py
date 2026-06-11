"""
2.6.1 — Execution-shape validation for the S1→S2 executor boundary.

Validates that actual executor output conforms to the expected output
shape/schema declared by a skill or primitive.  Also provides a simple
behavioural-anomaly heuristic for the drift-detection pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# JSON Schema → Python type mapping  (simplified subset)
# ---------------------------------------------------------------------------

_SCHEMA_TYPE_MAP: Dict[str, type] = {
    "object": dict,
    "dict": dict,
    "string": str,
    "str": str,
    "integer": int,
    "int": int,
    "number": float,
    "float": float,
    "boolean": bool,
    "bool": bool,
    "array": list,
    "list": list,
}


# ---------------------------------------------------------------------------
# ShapeValidationResult
# ---------------------------------------------------------------------------

@dataclass
class ShapeValidationResult:
    """Result of an execution-shape validation."""

    ok: bool
    message: str = ""
    details: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_type(value: Any, json_type_name: str) -> bool:
    """Return ``True`` if *value* is an instance of the Python type that
    corresponds to the simplified JSON Schema type name *json_type_name*."""
    py_type = _SCHEMA_TYPE_MAP.get(json_type_name.lower())
    if py_type is None:
        return True  # unknown type name — cannot validate
    return isinstance(value, py_type)


def _type_of(thing: Any) -> str:
    """Human-readable type name (mirrors what ``type(x).__name__`` returns)."""
    return type(thing).__name__


# ---------------------------------------------------------------------------
# validate_execution_shape
# ---------------------------------------------------------------------------

def validate_execution_shape(
    expected_schema: Optional[Dict[str, Any]],
    actual_output: Any,
) -> ShapeValidationResult:
    """
    Validate that *actual_output* conforms to *expected_schema*.

    Supports a simplified JSON Schema format:
      ``{"type": "object", "properties": {"x": {"type": "integer"}}}``

    When *expected_schema* is ``None`` validation is skipped (no contract
    to enforce).
    """
    if expected_schema is None:
        return ShapeValidationResult(ok=True)

    schema_type = expected_schema.get("type", "").lower()

    # -- Top-level type check -----------------------------------------------
    if schema_type in ("object", "dict"):
        if not isinstance(actual_output, dict):
            return ShapeValidationResult(
                ok=False,
                message=f"Expected dict, got {_type_of(actual_output)}",
                details={"expected_type": "dict", "actual_type": _type_of(actual_output)},
            )

        properties = expected_schema.get("properties", {})
        required = expected_schema.get("required", [])

        mismatches: list[str] = []

        # Check required fields exist
        for field_name in required:
            if field_name not in actual_output:
                mismatches.append(f"Missing required field '{field_name}'")

        # Check property types
        for field_name, field_schema in properties.items():
            # field_schema can be a plain string ("integer") or a dict
            # ({"type": "integer"}).  Normalise to string.
            if isinstance(field_schema, dict):
                expected_field_type = (field_schema.get("type") or "").lower()
            else:
                expected_field_type = str(field_schema).lower()

            actual = actual_output.get(field_name)
            if actual is not None and expected_field_type:
                if not _check_type(actual, expected_field_type):
                    mismatches.append(
                        f"'{field_name}': expected {expected_field_type}, "
                        f"got {_type_of(actual)}"
                    )

        if mismatches:
            return ShapeValidationResult(
                ok=False,
                message="; ".join(mismatches),
                details={
                    "mismatches": mismatches,
                    "expected_schema": expected_schema,
                    "actual_type": _type_of(actual_output),
                },
            )
        return ShapeValidationResult(ok=True)

    # -- Simple scalar types ------------------------------------------------
    if schema_type == "string" or schema_type == "str":
        ok = isinstance(actual_output, str)
        return ShapeValidationResult(
            ok=ok,
            message="" if ok else f"Expected str, got {_type_of(actual_output)}",
        )

    if schema_type in ("integer", "int"):
        ok = isinstance(actual_output, int)
        return ShapeValidationResult(
            ok=ok,
            message="" if ok else f"Expected int, got {_type_of(actual_output)}",
        )

    # -- Fallback: treat as pass-through ------------------------------------
    return ShapeValidationResult(ok=True)


# ---------------------------------------------------------------------------
# detect_behavioural_anomaly
# ---------------------------------------------------------------------------

def detect_behavioural_anomaly(
    expected_schema: Optional[Dict[str, Any]],
    actual_output: Any,
) -> Optional[str]:
    """
    Lightweight heuristic to detect a behavioural anomaly in the output.

    Operates alongside ``validate_execution_shape`` but looks for
    *unexpected presence* of output when none was declared, or for
    structural oddities that shape validation (which is type-focused)
    would miss.

    Returns ``None`` when output appears normal, or a short description
    of the suspected anomaly.
    """
    if expected_schema is None:
        if actual_output is not None:
            return "Output produced with no declared schema"
        return None

    schema_type = expected_schema.get("type", "").lower()

    if schema_type in ("object", "dict") and isinstance(actual_output, dict):
        properties = expected_schema.get("properties", {})
        if properties and actual_output:
            non_null = sum(1 for f in properties if actual_output.get(f) is not None)
            if non_null == 0:
                return "All declared fields are null"
    return None

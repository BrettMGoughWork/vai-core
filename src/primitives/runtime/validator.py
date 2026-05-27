from __future__ import annotations
from typing import Any, Dict

class ValidationError(Exception):
    pass


def validate_structural(schema: Dict[str, Any], args: Dict[str, Any]) -> None:
    """
    Validate that args structurally match the JSON schema.
    - required fields present
    - no unknown fields
    - types match
    """

    properties = schema.get("properties", {})
    required = schema.get("required", [])

    # 1. Check required fields
    for field in required:
        if field not in args:
            raise ValidationError(f"Missing required field: {field}")

    # 2. Check for unknown fields
    for field in args:
        if field not in properties:
            raise ValidationError(f"Unknown field: {field}")

    # 3. Type checking
    for field, value in args.items():
        expected = properties[field]
        _validate_type(field, value, expected)


def _validate_type(field: str, value: Any, expected_schema: Dict[str, Any]) -> None:
    expected_type = expected_schema.get("type")

    if expected_type == "integer" and not isinstance(value, int):
        raise ValidationError(f"Field '{field}' must be integer")

    if expected_type == "number" and not isinstance(value, (int, float)):
        raise ValidationError(f"Field '{field}' must be number")

    if expected_type == "boolean" and not isinstance(value, bool):
        raise ValidationError(f"Field '{field}' must be boolean")

    if expected_type == "string" and not isinstance(value, str):
        raise ValidationError(f"Field '{field}' must be string")

    if expected_type == "array" and not isinstance(value, list):
        raise ValidationError(f"Field '{field}' must be array")

    if expected_type == "object" and not isinstance(value, dict):
        raise ValidationError(f"Field '{field}' must be object")

    # fallback: accept anything
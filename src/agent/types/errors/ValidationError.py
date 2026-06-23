"""
Validation Error Class - Errors related to data or constraint validation.

ValidationError represents failures in input validation, constraint checking,
or type/schema validation.
"""

from typing import Any, Dict

from .AgentError import AgentError

from datetime import datetime, timezone

class ValidationError(AgentError, Exception):
    def __init__(self, message, details=None, timestamp=None, recoverable=False):
        if details is None:
            details = {}
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()
        super().__init__(
            type="ValidationError",
            message=message,
            details=details,
            timestamp=timestamp,
            recoverable=recoverable
        )
    def to_dict(self) -> dict:
        return super().to_dict()

    """
    Error raised when validation operations fail.

    Covers failures in input validation, constraint violations, type mismatches,
    and schema validation errors.
    """

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
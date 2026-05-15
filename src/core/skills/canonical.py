from __future__ import annotations
from typing import Any, Dict


def canonicalise_args(schema: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply simple canonicalisation rules based on schema:
    - trim strings
    - normalise whitespace
    - lowercase where appropriate (string only)
    - coerce ints/floats when safe
    """

    properties = schema.get("properties", {})
    out: Dict[str, Any] = {}

    for field, value in args.items():
        expected = properties.get(field, {})
        out[field] = _canonicalise_value(value, expected)

    return out


def canonicalize_args(schema: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
    """
    American-spelling alias used by BaseSkill.
    """
    return canonicalise_args(schema, args)


def _canonicalise_value(value: Any, expected_schema: Dict[str, Any]) -> Any:
    t = expected_schema.get("type")

    # String canonicalisation
    if t == "string" and isinstance(value, str):
        v = value.strip()
        v = " ".join(v.split()) # collapse whitespace
        return v

    # Integer coercion
    if t == "integer":
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())

    # Number coercion
    if t == "number":
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                pass

    # Boolean coercion
    if t == "boolean" and isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "yes", "1"):
            return True
        if lowered in ("false", "no", "0"):
            return False

    # Arrays: canonicalise each element
    if t == "array" and isinstance(value, list):
        return value # deeper rules added later

    # Objects: leave as-is for now
    if t == "object" and isinstance(value, dict):
        return value

    # Fallback: return unchanged
    return value
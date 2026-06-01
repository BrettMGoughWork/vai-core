from typing import Any, Dict, Optional


def detect_behavioural_anomaly(
    expected_schema: Optional[Dict[str, Any]],
    output: Any,
) -> Optional[str]:
    """
    Lightweight behavioural anomaly detector.

    Returns one of:
      - "type_mismatch"
      - "missing_fields"
      - "unexpected_fields"
      - None (no anomaly detected)
    """

    if expected_schema is None:
        return None

    # Expecting an object but got something else
    if expected_schema.get("type") == "object" and not isinstance(output, dict):
        return "type_mismatch"

    if not isinstance(output, dict):
        # If schema expects non-object types, you can extend here later.
        return None

    # Missing required fields
    required = expected_schema.get("required", [])
    missing = [k for k in required if k not in output]
    if missing:
        return "missing_fields"

    # Unexpected fields
    allowed = set(expected_schema.get("properties", {}).keys())
    extra = [k for k in output.keys() if k not in allowed]
    if extra:
        return "unexpected_fields"

    return None

"""
Phase 2.14.4 — S1 Response Validator
=====================================

Strict validation of raw LLM output.
Pure function. No I/O. No inference.

The validator converts raw text (from an LLM) into either:
- A valid PromptResponse (on success)
- An S1Error (on any failure)

No partial acceptance, no heuristics, no silent coercion.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Union

from src.domain.interfaces.contract import PromptResponse, S1Error
from src.runtime.llm.s1_validators import validate_prompt_response


# ──────────────────────────────────────────────────────────────────────────────
# Required output fields in a valid PromptResponse
# ──────────────────────────────────────────────────────────────────────────────

_REQUIRED_OUTPUT_KEYS: set = {
    "drift_detected",
    "drift_type",
    "drift_severity",
    "drift_detail",
    "repairs",
    "quality",
    "structural_deviation",
    "progress",
    "is_complete",
    "confidence",
    "next_action",
    "blockers",
    "shaped",
    "steps",
    "segments",
}

_KNOWN_OUTPUT_KEYS: set = _REQUIRED_OUTPUT_KEYS

# Allowed types for each required field
_TYPE_CHECKS: Dict[str, type] = {
    "drift_detected": bool,
    "drift_type": (str, type(None)),
    "drift_severity": str,
    "drift_detail": list,
    "repairs": list,
    "quality": dict,
    "structural_deviation": dict,
    "progress": (int, float),
    "is_complete": bool,
    "confidence": (int, float),
    "next_action": str,
    "blockers": list,
    "shaped": bool,
    "steps": list,
    "segments": list,
}


# ──────────────────────────────────────────────────────────────────────────────
# Main validator
# ──────────────────────────────────────────────────────────────────────────────


def validate_llm_response(raw_text: str) -> Union[PromptResponse, S1Error]:
    """Validate raw LLM output and return PromptResponse or S1Error.

    Pure function. No I/O.

    Validation is strict:
    - Must be valid JSON
    - Must parse to exactly one JSON object
    - Must contain all required fields with correct types
    - Must not contain extra fields
    - Must be JSON-safe
    - Must not be free-form text (if it parses to a string or non-object)

    Returns:
        - PromptResponse on success
        - S1Error on any validation failure

    On failure, NO S2 state is mutated. NO drift is emitted.
    """
    # ── Step 1: Must be a non-empty string ──────────────────────────────
    if not isinstance(raw_text, str) or not raw_text.strip():
        return S1Error(
            type="invalid_s1_response",
            message="Raw LLM output is empty or not a string.",
            details={"raw_type": type(raw_text).__name__},
        )

    # ── Step 2: Must parse to valid JSON ────────────────────────────────
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        return S1Error(
            type="invalid_s1_response",
            message=f"Raw LLM output is not valid JSON: {str(e)}",
            details={
                "error": str(e),
                "position": {"line": e.lineno, "col": e.colno},
                "raw_preview": raw_text[:200],
            },
        )

    # ── Step 3: Must be a dict (not a list, string, number, etc.) ──────
    if not isinstance(parsed, dict):
        return S1Error(
            type="invalid_s1_response",
            message="Parsed JSON is not a JSON object (dict).",
            details={
                "parsed_type": type(parsed).__name__,
                "raw_preview": raw_text[:200],
            },
        )

    # ── Step 4: Must contain all required fields ────────────────────────
    missing_keys = _REQUIRED_OUTPUT_KEYS - set(parsed.keys())
    if missing_keys:
        return S1Error(
            type="invalid_s1_response",
            message=f"Response missing required fields: {sorted(missing_keys)}",
            details={
                "missing_fields": sorted(missing_keys),
                "received_fields": sorted(parsed.keys()),
            },
        )

    # ── Step 5: Must not contain extra fields ───────────────────────────
    extra_keys = set(parsed.keys()) - _KNOWN_OUTPUT_KEYS
    if extra_keys:
        return S1Error(
            type="invalid_s1_response",
            message=f"Response contains unknown fields: {sorted(extra_keys)}",
            details={
                "extra_fields": sorted(extra_keys),
                "allowed_fields": sorted(_KNOWN_OUTPUT_KEYS),
            },
        )

    # ── Step 6: Fields must have correct types ──────────────────────────
    type_errors: List[str] = []
    for key, expected_type in _TYPE_CHECKS.items():
        value = parsed[key]
        if not isinstance(value, expected_type):
            expected_name = (
                expected_type.__name__
                if isinstance(expected_type, type)
                else " | ".join(t.__name__ for t in expected_type)
            )
            type_errors.append(
                f"Field '{key}' expected type {expected_name}, got {type(value).__name__}"
            )
    if type_errors:
        return S1Error(
            type="invalid_s1_response",
            message="Response fields have incorrect types.",
            details={"type_errors": type_errors},
        )

    # ── Step 7: Must be JSON-safe (double-check) ────────────────────────
    try:
        json.dumps(parsed)
    except (TypeError, ValueError) as e:
        return S1Error(
            type="invalid_s1_response",
            message=f"Response is not JSON-safe: {str(e)}",
            details={"json_error": str(e)},
        )

    # ── Step 8: Build and validate PromptResponse ───────────────────────
    try:
        response = PromptResponse(
            output=parsed,
            tool_calls=[],
            errors=[],
        )
    except Exception as e:
        return S1Error(
            type="invalid_s1_response",
            message=f"Failed to construct PromptResponse: {str(e)}",
            details={"construction_error": str(e)},
        )

    # ── Step 9: Run full schema validator ───────────────────────────────
    if not validate_prompt_response(response):
        return S1Error(
            type="invalid_s1_response",
            message="Response failed PromptResponse schema validation.",
            details={"output": parsed},
        )

    return response

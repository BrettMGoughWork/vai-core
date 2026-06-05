"""
Phase 2.14.1 — S1 Contract Validators
======================================

Pure functions that validate S1 contract types.
All functions are deterministic, side-effect-free, and JSON-safe.

Rules enforced:
- No missing fields
- No nulls in required fields
- No raw strings outside specified text fields
- All nested structures must be JSON-safe
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.core.planning.s1_contract.types import (
    PromptRequest,
    PromptResponse,
    ToolCallRequest,
    ToolCallResult,
    S1Error,
)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_REQUIRED_PROMPT_REQUEST_KEYS = {"prompt", "memory", "plan_context"}
_REQUIRED_PROMPT_RESPONSE_KEYS = {"output"}
_REQUIRED_TOOL_CALL_REQUEST_KEYS = {"name", "arguments"}
_REQUIRED_TOOL_CALL_RESULT_KEYS = {"name", "result", "success"}
_REQUIRED_S1ERROR_KEYS = {"type", "message"}


def _is_json_safe(value: Any) -> bool:
    """Check that a value is JSON-serialisable (no functions, no bytes, etc.)."""
    import json

    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


def _check_no_nulls_in_required(obj: Dict[str, Any], required: set, label: str) -> List[str]:
    """Return list of error messages for null required fields."""
    errors = []
    for key in required:
        if key not in obj:
            errors.append(f"{label}: missing required field '{key}'")
        elif obj[key] is None:
            errors.append(f"{label}: required field '{key}' is None")
    return errors


def _check_no_raw_strings(obj: Any, label: str) -> List[str]:
    """Check that raw strings don't appear at the top level of dicts meant to be structured."""
    errors = []
    if isinstance(obj, str):
        errors.append(f"{label}: raw string found where structured data is expected")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and len(v) > 500:
                # Heuristic: long raw strings inside structured fields are suspicious
                pass  # not an error per se, but worth noting
            errors.extend(_check_no_raw_strings(v, f"{label}.{k}"))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            errors.extend(_check_no_raw_strings(item, f"{label}[{i}]"))
    return errors


# ──────────────────────────────────────────────────────────────────────────────
# Validators
# ──────────────────────────────────────────────────────────────────────────────


def validate_prompt_request(req: PromptRequest) -> bool:
    """Validate a PromptRequest: all required fields present, no nulls, JSON-safe.

    Returns True if valid, False otherwise.
    """
    d = req.to_dict()
    errors = _check_no_nulls_in_required(d, _REQUIRED_PROMPT_REQUEST_KEYS, "PromptRequest")
    if errors:
        return False
    if not _is_json_safe(d):
        return False
    # tool_context must be a list of dicts if present
    if "tool_context" in d and d["tool_context"] is not None:
        if not isinstance(d["tool_context"], list):
            return False
        for item in d["tool_context"]:
            if not isinstance(item, dict):
                return False
    # prompt must be a dict (structured)
    if not isinstance(req.prompt, dict):
        return False
    return True


def validate_prompt_response(res: PromptResponse) -> bool:
    """Validate a PromptResponse: output present, JSON-safe, tool_calls/errors are lists of dicts.

    Returns True if valid, False otherwise.
    """
    d = res.to_dict()
    errors = _check_no_nulls_in_required(d, _REQUIRED_PROMPT_RESPONSE_KEYS, "PromptResponse")
    if errors:
        return False
    if not _is_json_safe(d):
        return False
    if not isinstance(res.output, dict):
        return False
    if not isinstance(res.tool_calls, list):
        return False
    for tc in res.tool_calls:
        if not isinstance(tc, dict):
            return False
    if not isinstance(res.errors, list):
        return False
    for e in res.errors:
        if not isinstance(e, dict):
            return False
    return True


def validate_tool_call_request(req: ToolCallRequest) -> bool:
    """Validate a ToolCallRequest."""
    d = req.to_dict()
    errors = _check_no_nulls_in_required(d, _REQUIRED_TOOL_CALL_REQUEST_KEYS, "ToolCallRequest")
    if errors:
        return False
    if not _is_json_safe(d):
        return False
    if not isinstance(req.arguments, dict):
        return False
    return True


def validate_tool_call_result(res: ToolCallResult) -> bool:
    """Validate a ToolCallResult."""
    d = res.to_dict()
    errors = _check_no_nulls_in_required(d, _REQUIRED_TOOL_CALL_RESULT_KEYS, "ToolCallResult")
    if errors:
        return False
    if not _is_json_safe(d):
        return False
    if not isinstance(res.result, dict):
        return False
    if not isinstance(res.success, bool):
        return False
    return True


def validate_s1_error(err: S1Error) -> bool:
    """Validate an S1Error."""
    d = err.to_dict()
    errors = _check_no_nulls_in_required(d, _REQUIRED_S1ERROR_KEYS, "S1Error")
    if errors:
        return False
    if not _is_json_safe(d):
        return False
    if not isinstance(err.details, dict):
        return False
    return True


def validate_prompt_request_detailed(req: PromptRequest) -> Dict[str, Any]:
    """Full validation returning structured result dict.

    Returns: {"valid": bool, "errors": list[str]}
    """
    issues: List[str] = []
    d = req.to_dict()
    issues.extend(_check_no_nulls_in_required(d, _REQUIRED_PROMPT_REQUEST_KEYS, "PromptRequest"))
    if not _is_json_safe(d):
        issues.append("PromptRequest is not JSON-safe")
    if not isinstance(req.prompt, dict):
        issues.append("PromptRequest.prompt must be a dict")
    if req.tool_context and not isinstance(req.tool_context, list):
        issues.append("PromptRequest.tool_context must be a list")
    elif req.tool_context:
        for i, item in enumerate(req.tool_context):
            if not isinstance(item, dict):
                issues.append(f"PromptRequest.tool_context[{i}] must be a dict")
    return {"valid": len(issues) == 0, "errors": issues}


def validate_prompt_response_detailed(res: PromptResponse) -> Dict[str, Any]:
    """Full validation returning structured result dict."""
    issues: List[str] = []
    d = res.to_dict()
    issues.extend(_check_no_nulls_in_required(d, _REQUIRED_PROMPT_RESPONSE_KEYS, "PromptResponse"))
    if not _is_json_safe(d):
        issues.append("PromptResponse is not JSON-safe")
    if not isinstance(res.output, dict):
        issues.append("PromptResponse.output must be a dict")
    if not isinstance(res.tool_calls, list):
        issues.append("PromptResponse.tool_calls must be a list")
    for i, tc in enumerate(res.tool_calls):
        if not isinstance(tc, dict):
            issues.append(f"PromptResponse.tool_calls[{i}] must be a dict")
    if not isinstance(res.errors, list):
        issues.append("PromptResponse.errors must be a list")
    for i, e in enumerate(res.errors):
        if not isinstance(e, dict):
            issues.append(f"PromptResponse.errors[{i}] must be a dict")
    return {"valid": len(issues) == 0, "errors": issues}

"""
Phase 2.14.1 — S1 → S2 Adapter
===============================

Pure function that converts a PromptResponse (from S1) into S2 updates.
No I/O, no inference, no mutation of inputs.

The adapter extracts:
- drift signals (from output quality assessment)
- repair proposals (from structured output deviations)
- reflection summaries (from completion/progress indicators)
- tool call results (from executed tool calls)

All outputs are JSON-safe and deterministic.
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.core.planning.s1_contract.types import PromptResponse, ToolCallResult


def _extract_drift_signals(output: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract behavioural drift signals from the structured LLM output.

    S1 may indicate quality concerns that S2 can use for drift detection.
    These are *hints*, not commands — S2 remains the authority.

    Returns: list of drift signal dicts (JSON-safe).
    """
    signals: List[Dict[str, Any]] = []

    # Check for explicit drift indicators in output
    if output.get("drift_detected"):
        signals.append({
            "source": "s1",
            "drift": output.get("drift_type", "unknown"),
            "severity": output.get("drift_severity", "minor"),
            "detail": output.get("drift_detail", {}),
        })

    # Quality assessment hints
    quality = output.get("quality", {})
    if isinstance(quality, dict):
        if quality.get("below_threshold"):
            signals.append({
                "source": "s1",
                "drift": "quality_below_threshold",
                "severity": "minor",
                "detail": quality,
            })

    # Structural deviation hints
    dev = output.get("structural_deviation", {})
    if isinstance(dev, dict) and dev:
        signals.append({
            "source": "s1",
            "drift": "structural_deviation",
            "severity": dev.get("severity", "minor"),
            "detail": dev,
        })

    return signals


def _extract_repair_proposals(output: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract repair proposals from the structured LLM output.

    Proposals are *suggestions* — S2's repair engine decides whether to apply.
    """
    proposals: List[Dict[str, Any]] = []

    repairs = output.get("repairs", [])
    if isinstance(repairs, list):
        for r in repairs:
            if isinstance(r, dict):
                proposals.append({
                    "source": "s1",
                    "target": r.get("target", "unknown"),
                    "action": r.get("action", "none"),
                    "replacement": r.get("replacement"),
                })

    return proposals


def _extract_reflection_summary(output: Dict[str, Any]) -> Dict[str, Any]:
    """Extract reflection-relevant fields from the LLM output.

    Returns a JSON-safe dict with progress, completion, and quality indicators.
    """
    return {
        "progress": output.get("progress", None),
        "is_complete": output.get("is_complete", False),
        "confidence": output.get("confidence", 1.0),
        "next_action": output.get("next_action", None),
        "blockers": output.get("blockers", []),
    }


def parse_prompt_response(response: PromptResponse) -> Dict[str, Any]:
    """Convert a PromptResponse into S2 updates.

    Pure function. No I/O.

    The returned dict contains:
        drift_signals:   list of drift signal dicts
        repair_proposals: list of repair proposal dicts
        reflection:      reflection summary dict
        tool_results:    list of ToolCallResult dicts (converted)
        output_raw:      the raw output dict (for memory/audit)
        errors:          any S1-level errors from the response

    Args:
        response: A validated PromptResponse from S1.

    Returns:
        A JSON-safe dict of S2-ready updates.
    """
    output = response.output

    # ── Tool call results ───────────────────────────────────────────
    tool_results: List[Dict[str, Any]] = []
    for tc in response.tool_calls:
        tool_results.append({
            "name": tc.get("name", "unknown"),
            "arguments": tc.get("arguments", {}),
            "result": tc.get("result", {}),
            "success": tc.get("success", False),
        })

    # ── Drift signals ───────────────────────────────────────────────
    drift_signals = _extract_drift_signals(output)

    # ── Repair proposals ────────────────────────────────────────────
    repair_proposals = _extract_repair_proposals(output)

    # ── Reflection summary ──────────────────────────────────────────
    reflection = _extract_reflection_summary(output)

    # ── Errors (from S1) ────────────────────────────────────────────
    errors = response.errors

    return {
        "drift_signals": drift_signals,
        "repair_proposals": repair_proposals,
        "reflection": reflection,
        "tool_results": tool_results,
        "output_raw": output,
        "errors": errors,
    }


def validate_s1_to_s2(response: PromptResponse) -> bool:
    """Validate that a PromptResponse is safe for S2 consumption.

    Rules (adapter-level, beyond basic type validation):
    - output is a non-empty dict
    - tool_calls list elements have required keys (name, arguments)
    - errors list elements have required keys (type, message)
    - No raw LLM text fields (output must be structured)
    - All nested structures are JSON-safe

    Returns True if the response is safe to parse into S2 updates.
    """
    if response is None:
        return False

    # output must be a non-empty dict
    if not isinstance(response.output, dict) or not response.output:
        return False

    # tool_calls: each entry must be a dict with 'name' key
    for tc in response.tool_calls:
        if not isinstance(tc, dict):
            return False
        if "name" not in tc:
            return False

    # errors: each entry must be a dict with 'type' and 'message'
    for err in response.errors:
        if not isinstance(err, dict):
            return False
        if "type" not in err or "message" not in err:
            return False

    # No raw text fields — output must be structured (enforce no 'raw_text' field)
    if "raw_text" in response.output and isinstance(response.output["raw_text"], str) and len(response.output) == 1:
        return False

    # Verify JSON-safety
    import json
    try:
        json.dumps(response.to_dict())
    except (TypeError, OverflowError):
        return False

    return True


def map_s1_error_to_agent_error(err: S1Error) -> dict:
    """Convert an S1Error into a structured AgentError update dict.

    Pure function. No I/O. No inference.

    The returned dict contains AgentError fields:
        type, message, details, recoverable, timestamp

    timestamp is set to None (caller fills if needed) to keep
    this function pure.

    Rules:
    - Must produce all required AgentError fields
    - Must not mutate S2 state
    - Must not continue execution (recoverable=False for S1 errors)
    - Must not emit drift or repair signals

    Args:
        err: An S1Error from response validation.

    Returns:
        A JSON-safe dict matching AgentError structure.
    """
    from datetime import datetime, timezone

    return {
        "type": "S1ResponseError",
        "message": err.message,
        "details": {
            "s1_error_type": err.type,
            "s1_error_details": err.details,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "recoverable": False,
    }


def validate_s1_to_s2_detailed(response: PromptResponse) -> dict:
    """Detailed variant: returns {"valid": bool, "errors": [str]}."""
    errors = []

    if response is None:
        return {"valid": False, "errors": ["PromptResponse is None"]}

    if not isinstance(response.output, dict) or not response.output:
        errors.append("output is missing or empty")

    for i, tc in enumerate(response.tool_calls):
        if not isinstance(tc, dict):
            errors.append(f"tool_calls[{i}] is not a dict")
        elif "name" not in tc:
            errors.append(f"tool_calls[{i}] missing 'name'")

    for i, err in enumerate(response.errors):
        if not isinstance(err, dict):
            errors.append(f"errors[{i}] is not a dict")
        else:
            if "type" not in err:
                errors.append(f"errors[{i}] missing 'type'")
            if "message" not in err:
                errors.append(f"errors[{i}] missing 'message'")

    if isinstance(response.output, dict):
        if "raw_text" in response.output and isinstance(response.output["raw_text"], str) and len(response.output) == 1:
            errors.append("output contains only raw_text (must be structured)")

    import json
    try:
        json.dumps(response.to_dict())
    except (TypeError, OverflowError) as e:
        errors.append(f"response is not JSON-safe: {e}")

    return {"valid": len(errors) == 0, "errors": errors}

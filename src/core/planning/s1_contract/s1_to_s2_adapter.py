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

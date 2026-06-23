"""
Phase 2.14.3 — S1 Simulation Backend
=====================================

Deterministic simulation of S1 (LLM/tooling) behaviour.
Pure function. No I/O. No inference. No randomness.

The simulation backend produces structured PromptResponse objects
by applying deterministic rules to the PromptRequest:
- Missing/invalid fields → structural drift signals
- Malformed plan_context → behavioural drift signals
- Otherwise → clean, successful response

All outputs are JSON-safe and identical across repeated calls
with the same input.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

from src.domain.interfaces.contract import PromptRequest, PromptResponse
from src.runtime.llm.s1_simulation_fixtures import (
    DEFAULT_DRIFT_OUTPUT,
    DEFAULT_REPAIR_OUTPUT,
    DEFAULT_REFLECTION_OUTPUT,
    DEFAULT_PLAN_SHAPING_OUTPUT,
)


# ──────────────────────────────────────────────────────────────────────────────
# Deterministic rules: detect structural issues in the request
# ──────────────────────────────────────────────────────────────────────────────


def _detect_missing_fields(request: PromptRequest) -> List[Dict[str, Any]]:
    """Check for missing required fields in the PromptRequest.

    Returns a list of drift signal dicts (empty if all fields present).
    """
    signals: List[Dict[str, Any]] = []

    # Required top-level fields
    if not isinstance(request.prompt, dict) or not request.prompt:
        signals.append({
            "drift_detected": True,
            "drift_type": "missing_prompt",
            "drift_severity": "major",
            "drift_detail": {"field": "prompt", "reason": "missing_or_empty"},
        })

    if not isinstance(request.memory, dict):
        signals.append({
            "drift_detected": True,
            "drift_type": "missing_memory",
            "drift_severity": "minor",
            "drift_detail": {"field": "memory", "reason": "not_a_dict"},
        })

    if not isinstance(request.plan_context, dict):
        signals.append({
            "drift_detected": True,
            "drift_type": "missing_plan_context",
            "drift_severity": "major",
            "drift_detail": {"field": "plan_context", "reason": "not_a_dict"},
        })

    # Nested: plan_context subgoal/segment
    if isinstance(request.plan_context, dict):
        subgoal = request.plan_context.get("subgoal")
        segment = request.plan_context.get("segment")

        if not isinstance(subgoal, dict):
            signals.append({
                "drift_detected": True,
                "drift_type": "missing_subgoal_context",
                "drift_severity": "major",
                "drift_detail": {"field": "plan_context.subgoal", "reason": "missing_or_not_a_dict"},
            })
        else:
            if "index" not in subgoal or subgoal["index"] is None:
                signals.append({
                    "drift_detected": True,
                    "drift_type": "missing_subgoal_index",
                    "drift_severity": "minor",
                    "drift_detail": {"field": "plan_context.subgoal.index", "reason": "missing_or_null"},
                })
            if "state" not in subgoal or subgoal["state"] is None:
                signals.append({
                    "drift_detected": True,
                    "drift_type": "missing_subgoal_state",
                    "drift_severity": "minor",
                    "drift_detail": {"field": "plan_context.subgoal.state", "reason": "missing_or_null"},
                })

        if not isinstance(segment, dict):
            signals.append({
                "drift_detected": True,
                "drift_type": "missing_segment_context",
                "drift_severity": "major",
                "drift_detail": {"field": "plan_context.segment", "reason": "missing_or_not_a_dict"},
            })
        else:
            if "index" not in segment or segment["index"] is None:
                signals.append({
                    "drift_detected": True,
                    "drift_type": "missing_segment_index",
                    "drift_severity": "minor",
                    "drift_detail": {"field": "plan_context.segment.index", "reason": "missing_or_null"},
                })
            if "state" not in segment or segment["state"] is None:
                signals.append({
                    "drift_detected": True,
                    "drift_type": "missing_segment_state",
                    "drift_severity": "minor",
                    "drift_detail": {"field": "plan_context.segment.state", "reason": "missing_or_null"},
                })

    # Prompt must have instruction
    if isinstance(request.prompt, dict) and "instruction" not in request.prompt:
        signals.append({
            "drift_detected": True,
            "drift_type": "missing_instruction",
            "drift_severity": "minor",
            "drift_detail": {"field": "prompt.instruction", "reason": "missing"},
        })

    return signals


def _detect_malformed_shapes(request: PromptRequest) -> List[Dict[str, Any]]:
    """Check for malformed shapes in the request that require normalisation.

    Returns a list of structural deviation signals.
    """
    signals: List[Dict[str, Any]] = []

    if isinstance(request.plan_context, dict):
        subgoal = request.plan_context.get("subgoal", {})
        segment = request.plan_context.get("segment", {})

        if isinstance(subgoal, dict):
            # subgoal index should be int >= -1
            idx = subgoal.get("index")
            if isinstance(idx, (int, float)) and isinstance(idx, float) and idx != int(idx):
                signals.append({
                    "drift_detected": True,
                    "drift_type": "non_integer_index",
                    "drift_severity": "minor",
                    "drift_detail": {"field": "plan_context.subgoal.index", "value": idx},
                })
            # subgoal state should be a known lifecycle value
            valid_states = {"pending", "running", "completed", "failed", "needs_repair"}
            state = subgoal.get("state")
            if isinstance(state, str) and state not in valid_states:
                signals.append({
                    "drift_detected": True,
                    "drift_type": "invalid_state",
                    "drift_severity": "minor",
                    "drift_detail": {"field": "plan_context.subgoal.state", "value": state, "valid": list(valid_states)},
                })

        if isinstance(segment, dict):
            idx = segment.get("index")
            if isinstance(idx, (int, float)) and isinstance(idx, float) and idx != int(idx):
                signals.append({
                    "drift_detected": True,
                    "drift_type": "non_integer_index",
                    "drift_severity": "minor",
                    "drift_detail": {"field": "plan_context.segment.index", "value": idx},
                })
            valid_states = {"pending", "running", "completed", "failed", "needs_repair"}
            state = segment.get("state")
            if isinstance(state, str) and state not in valid_states:
                signals.append({
                    "drift_detected": True,
                    "drift_type": "invalid_state",
                    "drift_severity": "minor",
                    "drift_detail": {"field": "plan_context.segment.state", "value": state, "valid": list(valid_states)},
                })

    return signals


# ──────────────────────────────────────────────────────────────────────────────
# Deterministic rules: generate repair proposals
# ──────────────────────────────────────────────────────────────────────────────


def _generate_repair_proposals(request: PromptRequest, drift_signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generate deterministic repair proposals based on detected drift signals.

    Each signal type maps to a specific repair action.
    """
    repairs: List[Dict[str, Any]] = []

    for signal in drift_signals:
        drift_type = signal.get("drift_type", "")
        field = signal.get("drift_detail", {}).get("field", "")

        if drift_type == "missing_prompt":
            repairs.append({
                "target": "prompt",
                "action": "fill_default",
                "replacement": {"instruction": "Execute the current subgoal and segment."},
            })

        elif drift_type == "missing_memory":
            repairs.append({
                "target": "memory",
                "action": "fill_default",
                "replacement": {},
            })

        elif drift_type == "missing_plan_context":
            repairs.append({
                "target": "plan_context",
                "action": "fill_default",
                "replacement": {"subgoal": {"index": 0, "state": "pending"}, "segment": {"index": 0, "state": "pending"}},
            })

        elif drift_type in ("missing_subgoal_context", "missing_subgoal_index", "missing_subgoal_state"):
            repairs.append({
                "target": "plan_context.subgoal",
                "action": "fill_default",
                "replacement": {"index": 0, "state": "pending"},
            })

        elif drift_type in ("missing_segment_context", "missing_segment_index", "missing_segment_state"):
            repairs.append({
                "target": "plan_context.segment",
                "action": "fill_default",
                "replacement": {"index": 0, "state": "pending"},
            })

        elif drift_type == "missing_instruction":
            repairs.append({
                "target": "prompt.instruction",
                "action": "fill_default",
                "replacement": "Execute the current subgoal and segment.",
            })

        elif drift_type == "invalid_state":
            repairs.append({
                "target": field,
                "action": "normalize",
                "replacement": "pending",
            })

        elif drift_type == "non_integer_index":
            repairs.append({
                "target": field,
                "action": "normalize",
                "replacement": 0,
            })

    return repairs


# ──────────────────────────────────────────────────────────────────────────────
# Deterministic rules: compute reflection summary
# ──────────────────────────────────────────────────────────────────────────────


def _compute_reflection(request: PromptRequest, has_drift: bool) -> Dict[str, Any]:
    """Compute a deterministic reflection summary based on the request state.

    Progress and completion are determined entirely from the plan_context indices.
    """
    if not isinstance(request.plan_context, dict):
        return deepcopy(DEFAULT_REFLECTION_OUTPUT)

    subgoal = request.plan_context.get("subgoal", {})
    segment = request.plan_context.get("segment", {})

    sg_state = subgoal.get("state", "unknown") if isinstance(subgoal, dict) else "unknown"
    seg_state = segment.get("state", "unknown") if isinstance(segment, dict) else "unknown"

    # Deterministic progress: based on lifecycle state
    state_progress = {
        "pending": 0.0,
        "running": 0.5,
        "needs_repair": 0.3,
        "completed": 1.0,
        "failed": 0.0,
    }
    seg_progress = state_progress.get(seg_state, 0.0)

    # Completion is true only when segment state is "completed"
    is_complete = seg_state == "completed"

    # Confidence decreases when drift is present
    confidence = 0.85 if has_drift else 0.95

    # Next action is deterministic based on state
    if seg_state == "completed":
        next_action = "advance_segment"
    elif has_drift:
        next_action = "repair_and_retry"
    elif seg_state == "pending":
        next_action = "execute_segment"
    elif seg_state == "running":
        next_action = "continue_execution"
    elif seg_state == "failed":
        next_action = "escalate"
    elif seg_state == "needs_repair":
        next_action = "repair"
    else:
        next_action = "continue"

    return {
        "progress": seg_progress,
        "is_complete": is_complete,
        "confidence": confidence,
        "next_action": next_action,
        "blockers": [],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Deterministic rules: plan shaping
# ──────────────────────────────────────────────────────────────────────────────


def _compute_plan_shaping(request: PromptRequest) -> Dict[str, Any]:
    """Compute deterministic plan shaping output.

    The simulation does not reshape plans; it returns an empty shaping result.
    """
    return deepcopy(DEFAULT_PLAN_SHAPING_OUTPUT)


# ──────────────────────────────────────────────────────────────────────────────
# Main simulation function
# ──────────────────────────────────────────────────────────────────────────────


def simulate_prompt_response(request: PromptRequest) -> PromptResponse:
    """Deterministic simulation of S1 behaviour.

    Pure function. No I/O. No inference. No randomness.

    Produces a structured PromptResponse by applying deterministic rules:
    1. Detect missing/malformed fields → drift signals
    2. Generate repair proposals for detected issues
    3. Compute reflection summary from plan_context state
    4. Compute plan shaping (always empty in simulation)

    Args:
        request: A PromptRequest from S2.

    Returns:
        A PromptResponse with structured output, tool calls, and errors.
    """
    # ── Step 1: Detect structural drift ──────────────────────────────────
    missing_signals = _detect_missing_fields(request)
    malformed_signals = _detect_malformed_shapes(request)
    all_drift_signals = missing_signals + malformed_signals  # deterministic order

    has_drift = len(all_drift_signals) > 0

    # ── Step 2: Generate repair proposals ─────────────────────────────────
    repair_proposals = _generate_repair_proposals(request, all_drift_signals)

    # ── Step 3: Compute reflection summary ───────────────────────────────
    reflection = _compute_reflection(request, has_drift)

    # ── Step 4: Compute plan shaping ─────────────────────────────────────
    plan_shaping = _compute_plan_shaping(request)

    # ── Build structured output ──────────────────────────────────────────
    output: Dict[str, Any] = {
        "drift_detected": has_drift,
        "drift_type": all_drift_signals[0]["drift_type"] if all_drift_signals else None,
        "drift_severity": all_drift_signals[0]["drift_severity"] if all_drift_signals else "minor",
        "drift_detail": all_drift_signals,
        "repairs": repair_proposals,
        "quality": {"below_threshold": has_drift},
        "structural_deviation": (
            all_drift_signals[0]["drift_detail"]
            if all_drift_signals
            else {}
        ),
        **reflection,
        **plan_shaping,
    }

    # Tool calls: simulation never produces tool calls
    tool_calls: List[Dict[str, Any]] = []

    # Errors: simulation never produces errors (only surface through drift)
    errors: List[Dict[str, Any]] = []

    return PromptResponse(
        output=output,
        tool_calls=tool_calls,
        errors=errors,
    )

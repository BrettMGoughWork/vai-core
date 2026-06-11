"""
Phase 2.14.1 — S2 → S1 Adapter
===============================

Pure function that converts S2 internal state into a structured PromptRequest.
No I/O, no inference, no mutation of inputs.

The adapter faithfully serialises the S2 execution cursor:
- subgoal state summary
- segment state summary
- agent state summary
- memory snapshot
- tool schemas (if available)

All outputs are JSON-safe.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.strategy.planning.s1_contract.types import PromptRequest


def _safe_summary(obj: Any) -> Dict[str, Any]:
    """Convert an object to a JSON-safe dict summary.

    If the object has a to_dict() method, use it.
    If it's a dataclass, use its __dict__.
    Otherwise, wrap in a dict.
    """
    if obj is None:
        return {}
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for fname in obj.__dataclass_fields__:
            val = getattr(obj, fname)
            # Convert enums to their values
            if hasattr(val, "value"):
                val = val.value
            result[fname] = val
        return result
    if isinstance(obj, dict):
        return obj
    return {"value": str(obj)}


def build_prompt_request(
    agent_state: Any,
    subgoal_state: Any,
    segment_state: Any,
    memory: Dict[str, Any],
    tool_schemas: Optional[List[Dict[str, Any]]] = None,
) -> PromptRequest:
    """Convert S2 internal state into a structured PromptRequest.

    Pure function. No I/O.

    Args:
        agent_state: Current AgentExecutionState or equivalent.
        subgoal_state: Current SubgoalExecutionState.
        segment_state: Current SegmentExecutionState.
        memory: Full memory snapshot (JSON-safe dict).
        tool_schemas: Optional list of tool schemas for S1.

    Returns:
        A PromptRequest ready for serialisation to S1.
    """
    # ── Structured prompt payload ──────────────────────────────────────
    prompt: Dict[str, Any] = {
        "instruction": "Execute the current subgoal and segment. Return structured output only.",
        "agent_cycle": getattr(agent_state, "cycle", 0) if agent_state is not None else 0,
    }

    # ── Plan context: summaries of subgoal/segment state ─────────────────
    plan_context: Dict[str, Any] = {
        "subgoal": {
            "index": getattr(subgoal_state, "index", -1) if subgoal_state is not None else -1,
            "state": (
                getattr(subgoal_state, "state", "unknown").value
                if hasattr(getattr(subgoal_state, "state", "unknown"), "value")
                else str(getattr(subgoal_state, "state", "unknown"))
            )
            if subgoal_state is not None
            else "unknown",
        },
        "segment": {
            "index": getattr(segment_state, "index", -1) if segment_state is not None else -1,
            "state": (
                getattr(segment_state, "state", "unknown").value
                if hasattr(getattr(segment_state, "state", "unknown"), "value")
                else str(getattr(segment_state, "state", "unknown"))
            )
            if segment_state is not None
            else "unknown",
        },
    }

    # ── Agent state summary ─────────────────────────────────────────────
    if agent_state is not None:
        plan_context["agent"] = {
            "is_complete": getattr(agent_state, "is_complete", False),
        }

    # ── Tool context ────────────────────────────────────────────────────
    tool_context = tool_schemas or []

    return PromptRequest(
        prompt=prompt,
        memory=memory,
        plan_context=plan_context,
        tool_context=tool_context,
    )


def validate_s2_to_s1(req: PromptRequest) -> bool:
    """Validate that a PromptRequest produced by build_prompt_request is safe for S1.

    Rules (adapter-level, beyond basic type validation):
    - All required fields present and non-None
    - plan_context contains subgoal + segment sections with valid index/state
    - prompt is a dict with no raw S2 objects
    - All nested structures are JSON-safe
    - No raw strings crossing the boundary (only structured JSON)

    Returns True if the request is safe to serialize and send to S1.
    """
    if req is None:
        return False

    # Required top-level fields
    if not isinstance(req.prompt, dict) or not req.prompt:
        return False
    if not isinstance(req.memory, dict):
        return False
    if not isinstance(req.plan_context, dict):
        return False
    if not isinstance(req.tool_context, list):
        return False

    # plan_context must have subgoal and segment sections
    subgoal = req.plan_context.get("subgoal")
    segment = req.plan_context.get("segment")
    if not isinstance(subgoal, dict) or not isinstance(segment, dict):
        return False

    # subgoal section: must have index (int >= 0 or -1 for unknown) and state (str)
    if not isinstance(subgoal.get("index"), int):
        return False
    if not isinstance(subgoal.get("state"), str):
        return False

    # segment section: same requirements
    if not isinstance(segment.get("index"), int):
        return False
    if not isinstance(segment.get("state"), str):
        return False

    # Prompt must have required fields
    if "instruction" not in req.prompt:
        return False

    # Verify JSON-safety: the entire request must serialize
    import json
    try:
        json.dumps(req.to_dict())
    except (TypeError, OverflowError):
        return False

    return True


def validate_s2_to_s1_detailed(req: PromptRequest) -> dict:
    """Detailed variant: returns {"valid": bool, "errors": [str]}."""
    errors = []

    if req is None:
        return {"valid": False, "errors": ["PromptRequest is None"]}

    if not isinstance(req.prompt, dict) or not req.prompt:
        errors.append("prompt is missing or empty")
    if not isinstance(req.memory, dict):
        errors.append("memory is not a dict")
    if not isinstance(req.plan_context, dict):
        errors.append("plan_context is not a dict")
    if not isinstance(req.tool_context, list):
        errors.append("tool_context is not a list")

    if isinstance(req.plan_context, dict):
        subgoal = req.plan_context.get("subgoal")
        segment = req.plan_context.get("segment")
        if not isinstance(subgoal, dict):
            errors.append("plan_context.subgoal is missing or not a dict")
        else:
            if not isinstance(subgoal.get("index"), int):
                errors.append("plan_context.subgoal.index is not an int")
            if not isinstance(subgoal.get("state"), str):
                errors.append("plan_context.subgoal.state is not a string")
        if not isinstance(segment, dict):
            errors.append("plan_context.segment is missing or not a dict")
        else:
            if not isinstance(segment.get("index"), int):
                errors.append("plan_context.segment.index is not an int")
            if not isinstance(segment.get("state"), str):
                errors.append("plan_context.segment.state is not a string")

    if isinstance(req.prompt, dict) and "instruction" not in req.prompt:
        errors.append("prompt.instruction is missing")

    import json
    try:
        json.dumps(req.to_dict())
    except (TypeError, OverflowError) as e:
        errors.append(f"request is not JSON-safe: {e}")

    return {"valid": len(errors) == 0, "errors": errors}

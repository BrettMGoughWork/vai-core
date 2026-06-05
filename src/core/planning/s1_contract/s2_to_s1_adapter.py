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

from src.core.planning.s1_contract.types import PromptRequest


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

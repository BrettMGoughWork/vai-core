"""
Phase 5.3 — Planning & Cognitive Loop
======================================

Pure orchestrator that uses existing S1 and S3 interfaces to run a
bounded cognitive loop for agent reasoning.

S5.3 does NOT:
- call LLMs directly
- define new planning schemas
- define new skill invocation types
- reimplement S2's agent loop
- dispatch or execute actions

It produces only declarative ActionIntents — resolution and dispatch
are handled by downstream layers (S5.3 itself does not act).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.agent.interfaces import (
    ActivatedAgentContext,
    ActionIntent,
    ACTION_CALL_TOOL_INTENT,
    ACTION_REQUEST_S4_JOB_INTENT,
    ACTION_AGENT_STEP_INTENT,
    CAP_CONVERSATIONAL,
    CAP_TOOL_USE,
    CAP_JOB_SUBMISSION,
)
from src.runtime.interfaces import (
    PromptRequest,
    PromptResponse,
    S1Error,
    call_runtime_backend,
)
from src.capabilities.interfaces import (
    SkillCallRequest,
    SkillResult,
    SkillRunner,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

S5_PLANNER_VERSION = "1.0"
"""Current version of the S5.3 cognitive loop schema."""

DEFAULT_BACKEND = "simulation"
"""Default S1 backend.  Switch to "real_llm" when ready."""

DEFAULT_MAX_ITERATIONS = 5
"""Maximum cognitive loop iterations to prevent runaway reasoning."""

CONFIDENCE_FALLBACK = 1.0
"""Fallback confidence when the model output does not include a value."""

# ---------------------------------------------------------------------------
# CognitiveLoopResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CognitiveLoopResult:
    """Result of running the S5.3 cognitive loop.

    Fields
    ------
    thought:
        The reasoning output from S1 (the ``PromptResponse.output`` dict).
        Treated as opaque by downstream layers — it is the model's
        structured reasoning, not an instruction.
    action_intents:
        Declarative action intents produced by interpreting the model's
        reasoning against the agent's resolved capabilities.
    skill_results:
        Optional results from S3 skill invocations made during the loop.
        Each entry is a ``SkillResult`` dict with request_id, success,
        output, and error.
    confidence:
        The model's self-assessed confidence (from PromptResponse output).
    errors:
        Any errors encountered during loop execution.  These are
        informational — the loop never crashes.
    iteration_count:
        How many iterations the loop actually ran (bounded by
        ``max_iterations``).
    """

    thought: Dict[str, Any] = field(default_factory=dict)
    action_intents: List[ActionIntent] = field(default_factory=list)
    skill_results: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = CONFIDENCE_FALLBACK
    errors: List[Dict[str, Any]] = field(default_factory=list)
    iteration_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.thought, dict):
            raise ValueError("thought must be a dict")
        if not isinstance(self.action_intents, list):
            raise ValueError("action_intents must be a list")
        if not isinstance(self.skill_results, list):
            raise ValueError("skill_results must be a list")
        if not isinstance(self.confidence, float) and not isinstance(self.confidence, int):
            raise ValueError("confidence must be a float or int")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be in [0.0, 1.0]")
        if not isinstance(self.errors, list):
            raise ValueError("errors must be a list")
        if not isinstance(self.iteration_count, int):
            raise ValueError("iteration_count must be an int")
        if self.iteration_count < 0:
            raise ValueError("iteration_count must be >= 0")


# ---------------------------------------------------------------------------
# S5 → S1 Adapter
# ---------------------------------------------------------------------------


def build_prompt_request(context: ActivatedAgentContext) -> PromptRequest:
    """Map a ``ActivatedAgentContext`` into a ``PromptRequest`` for S1.

    This is the **only** place where S5 constructs a PromptRequest.
    It does NOT reuse S2's ``s2_to_s1_adapter.build_prompt_request()``,
    which expects subgoal_state / segment_state — S5 has no concept of
    those.

    Pure function.  No I/O.  No side effects.
    """
    prompt: Dict[str, Any] = {
        "instruction": "Process this agent activation and produce structured reasoning.",
        "agent_id": context.envelope.agent_id,
        "message": context.envelope.message.message,
        "capabilities": context.context.resolved_capabilities,
        "system_constraints": context.context.system_constraints,
    }

    memory: Dict[str, Any] = {
        "conversation_history": context.context.conversation_history,
    }

    plan_context: Dict[str, Any] = {
        "agent_metadata": {
            "name": context.context.agent_metadata.identity.name,
            "description": context.context.agent_metadata.identity.description,
            "inputs": context.context.agent_metadata.inputs,
            "outputs": context.context.agent_metadata.outputs,
        },
        "routing_hints": context.context.routing_hints,
        "channel_metadata": context.context.channel_metadata,
        "correlation_id": context.envelope.activation_context.get("correlation_id", ""),
        "trace_id": context.envelope.activation_context.get("trace_id", ""),
    }

    return PromptRequest(
        prompt=prompt,
        memory=memory,
        plan_context=plan_context,
        tool_context=[],
    )


def validate_prompt_response_for_s5(response: PromptResponse) -> bool:
    """Validate that a ``PromptResponse`` is safe for S5 consumption.

    Rules (lighter than S2 validation — S5 treats output as opaque):
    - output is a non-None dict
    - JSON-safe (serialisable)

    Returns True if the response is safe to consume.
    """
    if response is None:
        return False
    if not isinstance(response.output, dict):
        return False

    import json

    try:
        json.dumps(response.to_dict())
    except (TypeError, OverflowError):
        return False

    return True


# ---------------------------------------------------------------------------
# S5 → S3 Adapter
# ---------------------------------------------------------------------------


def _invoke_skill(
    skill_name: str,
    arguments: Dict[str, Any],
    runner: SkillRunner,
) -> SkillResult:
    """Invoke a skill via the S3 ``SkillRunner``.

    The S5 → S3 adapter wraps ``SkillRunner.execute()`` with a fresh
    request_id.  This is the **only** path for S5 to call skills.
    """
    request = SkillCallRequest(
        skill_name=skill_name,
        arguments=arguments,
        request_id=str(uuid.uuid4()),
        context={},
    )
    return runner.execute(request)


# ---------------------------------------------------------------------------
# Action intent production
# ---------------------------------------------------------------------------


def _produce_action_intents(
    thought: Dict[str, Any],
    capabilities: List[str],
) -> List[ActionIntent]:
    """Interpret the model's reasoning and produce declarative action intents.

    In simulation mode the model output contains S2-flavoured fields
    (drift, repairs, reflection).  The cognitive loop maps the most
    relevant capability to a corresponding action intent type.

    Pure function.  Deterministic given the same inputs.
    """
    intents: List[ActionIntent] = []

    # If the model indicates task is complete, emit a conversational intent
    is_complete = thought.get("is_complete", False)
    if is_complete:
        intents.append(
            ActionIntent(
                type=ACTION_AGENT_STEP_INTENT,
                payload={"reasoning": "conversational_reply"},
                description="Agent produced final reasoning — deliver response",
            )
        )
        return intents

    # Map capabilities to action intents
    for cap in capabilities:
        if cap == CAP_CONVERSATIONAL and not intents:
            intents.append(
                ActionIntent(
                    type=ACTION_AGENT_STEP_INTENT,
                    payload={"reasoning": "conversational"},
                    description="Produce a conversational response",
                )
            )
        elif cap == CAP_TOOL_USE:
            intents.append(
                ActionIntent(
                    type=ACTION_CALL_TOOL_INTENT,
                    payload={"reasoning": thought},
                    description="Call a tool based on model reasoning",
                )
            )
        elif cap == CAP_JOB_SUBMISSION:
            intents.append(
                ActionIntent(
                    type=ACTION_REQUEST_S4_JOB_INTENT,
                    payload={"reasoning": thought},
                    description="Submit an S4 job based on model reasoning",
                )
            )

    # Fallback: always produce at least a conversational step intent
    if not intents:
        intents.append(
            ActionIntent(
                type=ACTION_AGENT_STEP_INTENT,
                payload={"reasoning": "fallback"},
                description="Fallback — produce conversational response",
            )
        )

    return intents


# ---------------------------------------------------------------------------
# Error fallback
# ---------------------------------------------------------------------------

_SAFE_FALLBACK_THOUGHT: Dict[str, Any] = {
    "message": "Safe fallback — cognitive loop encountered an unrecoverable error.",
    "is_complete": True,
    "confidence": 0.0,
}


def _make_fallback_result(errors: List[Dict[str, Any]]) -> CognitiveLoopResult:
    """Produce a safe fallback result when the loop cannot recover."""
    return CognitiveLoopResult(
        thought=_SAFE_FALLBACK_THOUGHT,
        action_intents=[
            ActionIntent(
                type=ACTION_AGENT_STEP_INTENT,
                payload={"reasoning": "fallback"},
                description="Safe fallback after cognitive loop error",
            )
        ],
        confidence=0.0,
        errors=errors,
        iteration_count=0,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_cognitive_loop(
    context: ActivatedAgentContext,
    *,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    backend: str = DEFAULT_BACKEND,
    skill_runner: Optional[SkillRunner] = None,
) -> CognitiveLoopResult:
    """Run the S5.3 cognitive loop.

    Pure orchestrator that:
    1. Builds a ``PromptRequest`` from the activated agent context
    2. Calls S1 (simulation or real_llm) for reasoning
    3. Interprets the model's output
    4. Optionally invokes skills via S3
    5. Produces declarative ``ActionIntent``s
    6. Repeats up to ``max_iterations`` times

    Parameters
    ----------
    context:
        The activated agent context from S5.2.
    max_iterations:
        Maximum number of loop iterations (default 5).
    backend:
        S1 backend — ``"simulation"`` (default) or ``"real_llm"``.
    skill_runner:
        Optional ``SkillRunner`` for invoking skills via S3.  If
        ``None``, skills are not invoked during the loop.

    Returns
    -------
    CognitiveLoopResult
        The consolidated result of the cognitive loop.  Never crashes
        — errors are captured in the result.

    Raises
    ------
    TypeError
        If *context* is not an ``ActivatedAgentContext``.
    """
    # ── Guard ─────────────────────────────────────────────────────────
    if not isinstance(context, ActivatedAgentContext):
        raise TypeError(
            f"context must be an ActivatedAgentContext instance, "
            f"got {type(context).__name__}"
        )
    if max_iterations < 1:
        raise ValueError("max_iterations must be >= 1")

    # ── 1. Build initial PromptRequest ────────────────────────────────
    request = build_prompt_request(context)

    # Accumulators
    all_action_intents: List[ActionIntent] = []
    all_skill_results: List[Dict[str, Any]] = []
    all_errors: List[Dict[str, Any]] = []
    final_thought: Dict[str, Any] = {}
    final_confidence: float = CONFIDENCE_FALLBACK
    iteration = 0

    # ── 2. Cognitive loop ─────────────────────────────────────────────
    while iteration < max_iterations:
        iteration += 1

        # 2a. Call S1 (with single retry on S1Error)
        response: Optional[PromptResponse] = None
        s1_error: Optional[S1Error] = None

        for attempt in range(2):  # retry once
            result = call_runtime_backend(request, backend=backend)

            if isinstance(result, S1Error):
                s1_error = result
                continue  # retry

            # Success
            response = result
            s1_error = None
            break

        if response is None or not validate_prompt_response_for_s5(response):
            err = s1_error if s1_error is not None else S1Error(
                type="invalid_response",
                message="PromptResponse failed S5 validation",
            )
            all_errors.append({"type": err.type, "message": err.message, "details": err.details})
            break  # cannot continue without a valid response

        # 2b. Extract thought and confidence
        final_thought = response.output
        final_confidence = float(
            response.output.get("confidence", CONFIDENCE_FALLBACK)
        )

        # 2c. Invoke skills via S3 (if applicable)
        if skill_runner is not None:
            skill_refs = response.output.get("skill_refs", [])
            if isinstance(skill_refs, list):
                for ref in skill_refs:
                    skill_name = ref.get("skill_name", "") if isinstance(ref, dict) else ""
                    skill_args = ref.get("arguments", {}) if isinstance(ref, dict) else {}
                    if skill_name:
                        try:
                            skill_result = _invoke_skill(skill_name, skill_args, skill_runner)
                            all_skill_results.append({
                                "request_id": skill_result.request_id,
                                "success": skill_result.success,
                                "output": skill_result.output,
                                "error": skill_result.error,
                            })
                        except Exception as exc:
                            all_skill_results.append({
                                "request_id": "",
                                "success": False,
                                "error": f"Skill invocation failed: {exc}",
                            })

        # 2d. Produce action intents
        action_intents = _produce_action_intents(
            final_thought,
            context.context.resolved_capabilities,
        )
        all_action_intents.extend(action_intents)

        # 2e. Check completion
        is_complete = final_thought.get("is_complete", False)
        if is_complete:
            break

    # ── 3. Return consolidated result ──────────────────────────────────
    if all_errors and not final_thought:
        return _make_fallback_result(all_errors)

    return CognitiveLoopResult(
        thought=final_thought,
        action_intents=all_action_intents,
        skill_results=all_skill_results,
        confidence=final_confidence,
        errors=all_errors,
        iteration_count=iteration,
    )

"""
Phase 2.14.7 — S1 Client Router
================================

Pure routing function that dispatches PromptRequests to the
appropriate S1 backend (simulation or real_llm).

- ``backend="simulation"`` → deterministic planner mock (Phase 2.14.3)
- ``backend="mock"``      → conversational stub for the S5 CLI demo
- ``backend="real_llm"``  → real LLM provider behind kill‑switch (Phase 2.14.7)

All raw LLM output is validated through ``validate_llm_response``
before being returned to S2.  S2 never sees raw text or malformed
responses.

Pure function for routing logic.  I/O only occurs inside the real
LLM client path.
"""

from __future__ import annotations

import json
from typing import Optional, Union

from src.strategy.planning.s1_contract.types import PromptRequest, PromptResponse, S1Error
from src.strategy.planning.s1_contract.s1_simulation_backend import simulate_prompt_response
from src.strategy.planning.s1_contract.s1_response_validator import validate_llm_response
from src.strategy.planning.s1_contract.s1_simulation_fixtures import (
    DEFAULT_DRIFT_OUTPUT,
    DEFAULT_REPAIR_OUTPUT,
    DEFAULT_REFLECTION_OUTPUT,
    DEFAULT_PLAN_SHAPING_OUTPUT,
)


_ALLOWED_BACKENDS = {"simulation", "mock", "conversational", "real_llm"}


def _generate_real_llm_raw_response(request: PromptRequest) -> str:
    """Generate a deterministic JSON string simulating raw LLM output.

    Pure function. No I/O. No inference.
    Used as a fallback when the real LLM is disabled or as a stub
    in tests that don't want to hit a live provider.
    """
    response_dict = {
        "drift_detected": False,
        "drift_type": None,
        "drift_severity": "minor",
        "drift_detail": [],
        "repairs": [],
        "quality": {"below_threshold": False},
        "structural_deviation": {},
        **DEFAULT_REFLECTION_OUTPUT,
        **DEFAULT_PLAN_SHAPING_OUTPUT,
    }
    return json.dumps(response_dict)


def _mock_response(message: str, agent_id: str) -> str:
    """Produce a simple conversational mock response for the CLI demo.

    This is **not** a real LLM response — it's a deterministic stub
    that exercises the full S5 pipeline (supervisor, cognitive loop,
    state persistence) with human-readable output.
    """
    haikus = [
        "Silent code compiles,\nA single bug lies waiting,\nThe evening grows long.",
        "Lights blink on the board,\nData streams across the wire,\nAll systems are go.",
        "An error message,\nDeep in the terminal logs,\nSpring rain on the roof.",
    ]
    import random
    haiku = random.choice(haikus)
    return (
        f"[{agent_id} v1.0] Here's your haiku:\n\n"
        f"{haiku}\n\n"
        f"---\n"
        f"_This is a mock response from the S5 agent pipeline. "
        f"The cognitive loop, supervisor, and state store are all wired correctly._"
    )


def _resolve_model(llm_raw: dict) -> str:
    """Resolve the active model from variant config.

    If model_variants and active_variant are set, use the variant mapping.
    Otherwise fall back to the top-level model field.
    Pure function.
    """
    variants = llm_raw.get("model_variants", {})
    active = llm_raw.get("active_variant", "")
    if variants and active in variants:
        return variants[active]
    return llm_raw.get("model", "default")


# ── DI slot: LLM transport (set by the composition root) ──────────
# S2 does NOT import S1 types to create a transport itself.
# The S5 composition root injects the transport via set_llm_transport().

_llm_transport: object | None = None
"""Module-level DI slot for the S1 LLM transport.

Set by the composition root during startup.
S2 never imports S1 internals to create a transport.
"""


def set_llm_transport(transport: object | None) -> None:
    """Inject an S1 LLM transport from the composition root (S5)."""
    global _llm_transport
    _llm_transport = transport


def _tool_matches_workflows(tool: dict, agent_workflows: list[str]) -> bool:
    """Check if a tool definition matches one of the agent's allowed workflows.

    Supports the ``workflow.execute.<id>`` naming convention used by
    ``WorkflowToolAdapter``, as well as bare workflow IDs.
    A wildcard ``"*"`` in agent_workflows matches everything.
    """
    if "*" in agent_workflows:
        return True
    name = tool.get("function", {}).get("name", "") or tool.get("name", "")
    # Extract workflow ID from "workflow.execute.<id>" or use bare name
    wf_id = name
    for prefix in ("workflow.execute.", "workflow."):
        if wf_id.startswith(prefix):
            wf_id = wf_id[len(prefix):]
            break
    return wf_id in agent_workflows or name in agent_workflows



def call_s1_backend(
    request: PromptRequest, backend: str = "simulation"
) -> Union[PromptResponse, S1Error]:
    """Route a PromptRequest to the specified S1 backend.

    Args:
        request: A validated PromptRequest from S2.
        backend: One of ``"simulation"`` (default, deterministic) or
                 ``"real_llm"`` (live LLM behind kill‑switch).

    Returns:
        A PromptResponse on success, or an S1Error if:
          - The kill‑switch is active (``ENABLE_REAL_LLM=False``)
          - The LLM returns invalid/malformed output
          - The provider call fails irrecoverably

    Raises:
        ValueError: If backend is not recognised.
    """
    if backend not in _ALLOWED_BACKENDS:
        raise ValueError(
            f"Unknown backend: {backend!r}. Allowed: {sorted(_ALLOWED_BACKENDS)}"
        )

    if backend == "simulation":
        return simulate_prompt_response(request)

    if backend == "mock":
        message = request.prompt.get("message", "(no message)")
        agent_id = request.prompt.get("agent_id", "unknown")
        return PromptResponse(
            output={
                "is_complete": True,
                "message": _mock_response(message, agent_id),
                "confidence": 0.95,
            },
        )

    # ── conversational path ───────────────────────────────────────────────
    # Sends the user message directly to a real LLM and wraps the response
    # into the format the S5 supervisor expects.
    if backend == "conversational":
        if _llm_transport is None:
            return S1Error(
                type="llm_transport_unavailable",
                message="No LLM transport configured. The composition root must inject one via set_llm_transport().",
                details={"hint": "Call set_llm_transport(transport) in the composition root before use."},
            )

        transport = _llm_transport

        user_message = request.prompt.get("message", "")
        agent_id = request.prompt.get("agent_id", "assistant")
        agent_metadata = request.prompt.get("agent_metadata", {})
        agent_name = agent_metadata.get("name", agent_id)
        description = agent_metadata.get("description", "")
        persona = agent_metadata.get("persona", "")
        agent_workflows = agent_metadata.get("workflows", [])

        # Allow workflow YAMLs to override the system prompt
        explicit_system_prompt = request.prompt.get("system_prompt")
        if explicit_system_prompt:
            system_prompt = explicit_system_prompt
        else:
            system_prompt = (
                f"You are {agent_name}, an AI assistant in the VAI platform.\n"
                f"Role: {persona}\n"
                f"Description: {description}\n\n"
                "Respond conversationally. Be concise, helpful, and accurate."
            )

        # Inject agent capabilities — available workflows
        cap_lines = []
        if agent_workflows:
            if "*" in agent_workflows:
                # Derive actual workflow names from tool_context for display
                wf_names = sorted({
                    t.get("name", "").replace("workflow.execute.", "")
                    for t in (request.tool_context or [])
                    if t.get("name", "")
                })
                if wf_names:
                    cap_lines.append("\nYour available workflows:\n" + "\n".join(f"  - {w}" for w in wf_names))
                else:
                    cap_lines.append("\nYou have access to all available workflows.")
            else:
                cap_lines.append("\nYour available workflows:\n" + "\n".join(f"  - {w}" for w in agent_workflows))
        if cap_lines:
            system_prompt += "".join(cap_lines)

        # Inject workflow tool descriptions so the LLM can discover and
        # invoke workflows.  Only include workflows the agent has access to.
        # The LLM invokes one by including a line like:
        #   /invoke-workflow <workflow_id> param1=value1 param2=value2
        all_tool_context = request.tool_context or []

        # ── Workflow tools ───────────────────────────────────────────
        wf_tool_context = [
            t for t in all_tool_context
            if not agent_workflows or _tool_matches_workflows(t, agent_workflows)
        ]
        if wf_tool_context:
            tool_lines = []
            for tool in wf_tool_context:
                # Support both flat format (adapter) and OpenAI function-wrapper format
                func = tool.get("function")
                if func is not None:
                    name = func.get("name", "unknown")
                    desc = func.get("description", "")
                    params = func.get("parameters", {})
                else:
                    name = tool.get("name", "unknown")
                    desc = tool.get("description", "")
                    params = tool.get("input_schema", tool.get("parameters", {}))
                props = params.get("properties", {})
                param_strs = []
                for pname, pinfo in props.items():
                    req = "required" if pname in params.get("required", []) else "optional"
                    param_strs.append(f"    - {pname} ({req}): {pinfo.get('description', '')}")
                tool_lines.append(f"\n  **{name}**: {desc}")
                if param_strs:
                    tool_lines.append("    Parameters:")
                    tool_lines.extend(param_strs)
            if tool_lines:
                system_prompt += (
                    "\n\nYou have access to the following workflows which you can invoke "
                    "when a user's request matches their purpose.\n"
                    "To invoke a workflow, include a line in your response exactly in the format:\n"
                    '/invoke-workflow <workflow_id> key1="value1" key2="value2"\n'
                    "You may invoke one or more workflows \u2014 one per line."
                )
                system_prompt += "".join(tool_lines)

        # Format the history block from prior turns
        conversation_history = request.memory.get("conversation_history", [])
        if conversation_history:
            history_lines: list[str] = []
            for entry in conversation_history:
                role = entry.get("role", "user")
                content = entry.get("content", "")
                label = "User" if role == "user" else agent_name
                history_lines.append(f"{label}: {content}")
            history_block = "\n".join(history_lines) + "\n"
        else:
            history_block = ""

        try:
            if history_block:
                raw_text = transport.complete(
                    f"{system_prompt}\n\n{history_block}"
                    f"User: {user_message}\n{agent_name}:"
                )
            else:
                raw_text = transport.complete(
                    f"{system_prompt}\n\n"
                    f"User: {user_message}\n{agent_name}:"
                )
            import time
            return PromptResponse(
                output={
                    "is_complete": True,
                    "message": raw_text.strip(),
                    "confidence": 0.95,
                },
            )
        except Exception as exc:
            return S1Error(
                type="conversational_llm_failure",
                message=f"Conversational LLM call failed: {str(exc)}",
                details={"exception_type": type(exc).__name__},
            )

    # ── real_llm path ────────────────────────────────────────────────────

    # 1. Kill‑switch — check before any network call
    from src.strategy.planning.s1_contract.s1_real_client import ENABLE_REAL_LLM

    if not ENABLE_REAL_LLM:
        return S1Error(
            type="real_llm_disabled",
            message="Kill-switch active — real LLM backend is not enabled.",
            details={
                "hint": "Set ENABLE_REAL_LLM=True in s1_real_client.py only after "
                        "passing the readiness checklist (Phase 2.14.6)."
            },
        )

    # 2. Call the real LLM (may raise S1RealLLMError)
    try:
        from src.strategy.planning.s1_contract.s1_real_client import call_llm
        raw_text = call_llm(request)
    except Exception as exc:
        return S1Error(
            type="s1_provider_failure",
            message=f"Real LLM call failed: {str(exc)}",
            details={"exception_type": type(exc).__name__},
        )

    # 3. Validate → PromptResponse | S1Error
    return validate_llm_response(raw_text)


# Domain-name alias — call_runtime_backend is the canonical name.
call_runtime_backend = call_s1_backend

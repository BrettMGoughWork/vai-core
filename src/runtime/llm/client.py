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
import os
import re
import sys
from collections import Counter
from typing import Optional, Union

from src.domain.interfaces.contract import PromptRequest, PromptResponse, S1Error
from src.runtime.llm.s1_simulation_backend import simulate_prompt_response
from src.runtime.llm.s1_response_validator import validate_llm_response
from src.runtime.llm.token_counter import count_tokens_in_messages, count_tokens_in_tools, get_context_limit
from src.runtime.llm.s1_simulation_fixtures import (
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


# ── DI slot: CompactionOrchestrator (set by the composition root) ─────
# Avoids circular imports — agent/ imports client.py, so client.py cannot
# import agent/.

_compaction_orchestrator: object | None = None
"""Module-level DI slot for the CompactionOrchestrator."""


def set_compaction_orchestrator(orchestrator: object | None) -> None:
    """Inject the CompactionOrchestrator from the composition root."""
    global _compaction_orchestrator
    _compaction_orchestrator = orchestrator


# ── DI slot: EvictionOrchestrator (set by the composition root) ────────
# Same pattern as CompactionOrchestrator above — avoids circular imports.

_eviction_orchestrator: object | None = None
"""Module-level DI slot for the EvictionOrchestrator."""


def set_eviction_orchestrator(orchestrator: object | None) -> None:
    """Inject the EvictionOrchestrator from the composition root."""
    global _eviction_orchestrator
    _eviction_orchestrator = orchestrator


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


def _is_primitive_tool(tool: dict) -> bool:
    """Check if a tool definition is a primitive tool (starts with ``primitive.``)."""
    name = tool.get("function", {}).get("name", "") or tool.get("name", "")
    return name.startswith("primitive.")


_NON_SAFE_NAME_CHARS = re.compile(r"[^a-zA-Z0-9_-]")


def _sanitize_tool_name(name: str) -> str:
    """Sanitize a tool name for LLM providers.

    Most providers require tool/function names matching ``^[a-zA-Z0-9_-]+$``
    (OpenAI API spec).  We replace any non-compliant character with ``_``.

    Local ``name_map`` returned by ``_to_openai_tools`` allows reversal.
    """
    return _NON_SAFE_NAME_CHARS.sub("_", name)


def _restore_tool_name(name: str, name_map: dict[str, str]) -> str:
    """Reverse-map a sanitised tool name to its original form.

    Tries an exact lookup first.  If the LLM returned a name that's not
    in the map (e.g. because the provider re-mixed dots and underscores),
    falls back to re-sanitising the name with the same dots→underscores
    transform used by ``_to_openai_tools`` before trying again.
    """
    if name in name_map:
        return name_map[name]
    # Providers like DeepSeek sometimes return names with mixed dots/underscores
    # that don't exactly match the sanitised key.  Re-sanitise and retry.
    retry = name.replace(".", "_")
    return name_map.get(retry, name)


def _to_openai_tools(tool_context: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """Normalize tool definitions to OpenAI-compatible format.

    Supports both flat adapter format (``{name, description, input_schema}``)
    and OpenAI function-wrapper format (``{type: "function", function: {...}}``).

    **Name sanitisation**: tool names are sanitised to match ``^[a-zA-Z0-9_-]+$``
    (the OpenAI API spec, supported by most providers).  Returns a
    ``(tools, name_map)`` tuple where ``name_map`` is ``sanitised → original``.
    """
    name_map: dict[str, str] = {}
    result: list[dict] = []
    for tool in tool_context:
        if tool.get("type") == "function":
            result.append(tool)
            continue
        func = tool.get("function")
        if func:
            name = func.get("name", tool.get("name", "unknown"))
            desc = func.get("description", tool.get("description", ""))
            params = func.get("parameters", tool.get("input_schema", {}))
        else:
            name = tool.get("name", "unknown")
            desc = tool.get("description", "")
            params = tool.get("input_schema", tool.get("parameters", {}))
        safe_name = _sanitize_tool_name(name)
        if safe_name != name:
            name_map[safe_name] = name

        # Ensure at least one param is required when the schema has
        # properties but no ``required`` list — prevents LLMs from
        # calling tools with empty ``{}`` arguments.
        if isinstance(params, dict) and "properties" in params and "required" not in params:
            props = params.get("properties", {})
            if props:
                params = dict(params)  # shallow copy
                first_prop = next(iter(props.keys()))
                params["required"] = [first_prop]
                if os.environ.get("S1_DEBUG"):
                    print(f"[S1_DEBUG] Tool '{safe_name}': added required=[{first_prop!r}]", file=sys.stderr)
        result.append({
            "type": "function",
            "function": {
                "name": safe_name,
                "description": desc,
                "parameters": params,
            },
        })
    return result, name_map


def _restore_tool_names_in_response(
    tool_calls: list[dict],
    name_map: dict[str, str],
) -> list[dict]:
    """Restore original tool names in a list of tool_call dicts.

    Mutates and returns the same list (in-place update of both
    ``function.name`` and top-level ``name`` — the orchestrator reads
    both paths).
    """
    for tc in tool_calls:
        func = tc.get("function", {})
        if isinstance(func, dict) and "name" in func:
            func["name"] = _restore_tool_name(func["name"], name_map)
        # Some providers (and the orchestrator) use tc["name"] directly
        if "name" in tc:
            tc["name"] = _restore_tool_name(tc["name"], name_map)
    return tool_calls


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
            try:
                workspace_dir = os.getcwd()
            except OSError:
                workspace_dir = os.path.expanduser("~")
            system_prompt = (
                f"You are {agent_name}, an AI assistant in the VAI platform.\n"
                f"Role: {persona}\n"
                f"Description: {description}\n"
                f"Workspace directory: {workspace_dir}\n\n"
                "Respond conversationally. Be concise, helpful, and accurate."
                "\nWhen creating or reading files via stdlib.file.* primitives,"
                " use paths relative to the workspace directory unless an absolute path is required."
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

        # Inject agent capabilities — pattern instructions
        agent_patterns = agent_metadata.get("patterns", [])
        if agent_patterns:
            pattern_lines = ["\nYou have received the following operational guidance (patterns):"]
            for p in agent_patterns:
                pid = p.get("pattern_id", "unknown")
                pname = p.get("name", pid)
                instr = p.get("instructions", "")
                pattern_lines.append(f"\n--- Pattern: {pname} ({pid}) ---")
                pattern_lines.append(instr)
                pattern_lines.append(f"--- End Pattern: {pname} ---")
            system_prompt += "\n".join(pattern_lines)

        # Inject agent capabilities — available councils for deliberation
        agent_councils = agent_metadata.get("councils", [])
        if agent_councils:
            council_lines = [
                "\n\nYou have the following councils available for deliberation."
            ]
            for c in agent_councils:
                cid = c.get("council_id", "unknown")
                cname = c.get("name", cid)
                cdesc = c.get("description", "")
                members = c.get("members", [])
                arbitrator = c.get("arbitrator", "")
                council_lines.append(f"\n- {cname} ({cid}): {cdesc}")
                if members:
                    council_lines.append(
                        f"  Members: {', '.join(str(m) for m in members)}"
                    )
                if arbitrator:
                    council_lines.append(f"  Arbitrator: {arbitrator}")
            council_lines.append(
                "\n\nTo convene a council, call the `convene_council` tool "
                "with the council_id and your problem description."
            )
            system_prompt += "\n".join(council_lines)

        # ── Build tool definitions and prepare for native function calling ──
        all_tool_context = request.tool_context or []

        # Keep tools the agent can use:
        #   - Workflow tools matching the agent's workflow list
        #   - Primitive tools (primitive.*) — always included regardless of
        #     workflow filter, since primitives aren't workflows
        kept_tool_context = [
            t for t in all_tool_context
            if (
                not agent_workflows
                or _tool_matches_workflows(t, agent_workflows)
                or _is_primitive_tool(t)
            )
        ]

        # Convert to OpenAI-compatible tool definitions
        tools, tool_name_map = _to_openai_tools(kept_tool_context) if kept_tool_context else ([], {})

        # ── Token counting & model resolution (needed by compaction below) ─
        conversation_history = request.memory.get("conversation_history", [])
        model_name = _resolve_model(request.prompt) if request.prompt else ""
        output_budget = request.prompt.get("max_tokens", 4096) if request.prompt else 4096

        # Pre-count tokens for compaction trigger if orchestrator is active
        # (the full count is re-done after compaction + message building below).
        pre_count = count_tokens_in_messages(conversation_history) if conversation_history else 0
        context_limit = get_context_limit(model_name, output_budget=output_budget)
        pre_pressure = (pre_count / context_limit) if context_limit else 0.0

        # ── Compaction pass — compress older turns before building messages ─
        if _compaction_orchestrator is not None and conversation_history:
            try:
                result = _compaction_orchestrator.compact_if_needed(
                    conversation_history=conversation_history,
                    model=model_name,
                    max_tokens=output_budget,
                    context_pressure=pre_pressure,
                )
                # Trigger eviction for subgoals whose episodes were compacted
                if (
                    result is not None
                    and getattr(result, "triggered", False)
                    and not getattr(result, "rolled_back", False)
                    and _eviction_orchestrator is not None
                ):
                    compacted_ids = getattr(result, "compacted_subgoal_ids", set())
                    if compacted_ids:
                        _eviction_orchestrator.on_episode_compacted(
                            compacted_subgoal_ids=compacted_ids,
                        )
            except Exception:
                pass  # compaction failure should never crash the LLM call

        # Build structured message list: system, conversation history, user
        #
        # SECURITY: Session history (SessionedAdapter._build_history) stores
        # ``tool_calls`` in assistant entries but does NOT store the
        # corresponding ``tool`` role messages with ``tool_call_id`` (tool
        # results).  Sending an assistant message with ``tool_calls`` but
        # without a matching ``tool`` message creates an invalid message
        # sequence that many LLM providers reject — this causes an
        # S1Error → strategy_router falls back to mock → haiku loop.
        #
        # To prevent this, we strip ``tool_calls`` from any conversation
        # history entry if there is no following ``tool`` message with a
        # matching ``tool_call_id`` in the same history slice.
        #
        # First pass: collect all tool_call_ids present in the history.
        # We use a Counter so that we can implement order-aware matching:
        # each ``tool`` message pairs with exactly *one* preceding
        # ``assistant`` entry.  If the same tool_call_id appears in
        # multiple assistant entries (because ``_build_history``
        # duplicated the ``llm_tool_calls``), only the first encounter
        # is included; subsequent encounters are stripped — they have
        # no matching tool message.
        available_tool_call_ids: Counter = Counter()
        for entry in conversation_history:
            if entry.get("role") == "tool":
                tcid = entry.get("tool_call_id")
                if isinstance(tcid, str) and tcid:
                    available_tool_call_ids[tcid] += 1

        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        for entry in conversation_history:
            role = entry.get("role", "user")
            content = entry.get("content") or ""  # or "" guards against None stored in session
            if role in ("user", "assistant", "tool"):
                msg: dict[str, object] = {"role": role, "content": content}
                if role == "assistant" and "tool_calls" in entry and available_tool_call_ids:
                    # Order-aware matching: each tool_call_id must have
                    # a *following* tool message.  We consume one
                    # occurrence per assistant entry that references it,
                    # so that later duplicates are correctly stripped.
                    paired: list[dict] = []
                    for tc in entry["tool_calls"]:
                        if not isinstance(tc, dict):
                            continue
                        tcid = tc.get("id", "")
                        if not tcid or tc.get("function", {}).get("name") == "":
                            paired.append(tc)
                            continue
                        if available_tool_call_ids.get(tcid, 0) > 0:
                            available_tool_call_ids[tcid] -= 1
                            paired.append(tc)
                    if paired:
                        msg["tool_calls"] = paired
                if role == "tool" and "tool_call_id" in entry:
                    msg["tool_call_id"] = entry["tool_call_id"]
                messages.append(msg)

        messages.append({"role": "user", "content": user_message})

        # ── Token counting for context-pressure tracking ────────
        input_tokens = count_tokens_in_messages(messages) + count_tokens_in_tools(tools)
        context_limit = get_context_limit(model_name, output_budget=output_budget)
        context_pressure = (input_tokens / context_limit) if context_limit else 0.0

        try:
            if tools and hasattr(transport, "complete_with_tools"):
                # ── Native tool calling path ───────────────────────────────
                response = transport.complete_with_tools(messages, tools)

                if response.tool_name and response.tool_calls:
                    # LLM chose to call a tool — return tool_calls for the
                    # supervisor to execute (with HITL gating if needed)
                    #
                    # Restore original tool names (dots → underscores
                    # mapping applied during send, reverse here).
                    if os.environ.get("S1_DEBUG"):
                        print(f"[S1_DEBUG] LLM returned tool_calls: {response.tool_calls}", file=sys.stderr)
                    _restore_tool_names_in_response(response.tool_calls, tool_name_map)
                    if os.environ.get("S1_DEBUG"):
                        print(f"[S1_DEBUG] After name restore: {response.tool_calls}", file=sys.stderr)
                    return PromptResponse(
                        output={
                            "is_complete": False,
                            "message": response.text or "",
                            "confidence": 0.95,
                        },
                        tool_calls=response.tool_calls,
                        input_tokens=input_tokens,
                        context_pressure=context_pressure,
                    )

                # LLM returned a text response (no tool chosen)
                return PromptResponse(
                    output={
                        "is_complete": True,
                        "message": response.text.strip() if response.text else "",
                        "confidence": 0.95,
                    },
                    input_tokens=input_tokens,
                    context_pressure=context_pressure,
                )
            else:
                # ── Fallback: text-only path (no tools available) ──────────
                if conversation_history:
                    raw_text = transport.complete(
                        f"{system_prompt}\n\n"
                        f"{'  '.join(f'{e.get("role","user")}: {e.get("content","")}' for e in conversation_history)}\n"
                        f"User: {user_message}\n{agent_name}:"
                    )
                else:
                    raw_text = transport.complete(
                        f"{system_prompt}\n\n"
                        f"User: {user_message}\n{agent_name}:"
                    )
                return PromptResponse(
                    output={
                        "is_complete": True,
                        "message": raw_text.strip(),
                        "confidence": 0.95,
                    },
                    input_tokens=input_tokens,
                    context_pressure=context_pressure,
                )
        except Exception as exc:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.error(
                "S1 conversational LLM call failed — triggering mock fallback. "
                "exception_type=%s, exception_message=%s, full_exc=%r",
                type(exc).__name__, str(exc), exc,
            )
            return S1Error(
                type="conversational_llm_failure",
                message=f"Conversational LLM call failed: {str(exc)}",
                details={"exception_type": type(exc).__name__},
            )

    # ── real_llm path ────────────────────────────────────────────────────

    # 1. Kill‑switch — check before any network call
    from src.runtime.llm.s1_real_client import ENABLE_REAL_LLM

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
        from src.runtime.llm.s1_real_client import call_llm
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

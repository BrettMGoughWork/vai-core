"""
Tool orchestrator for executing agent tool calls.

Owns the phase-1 tool execution loop (workflow.execute.* and primitive.*)
and the phase-2 follow-up LLM call that feeds tool results back into
conversation context.

Extracted from supervisor.py per Sprint 18.3.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from src.agent.workflow.engine import WorkflowExecutionState, WorkflowStatus


# ---------------------------------------------------------------------------
# Module-level helpers (shared with workflow_invoker)
# ---------------------------------------------------------------------------

from src.agent.workflow_invoker import _render_context_templates  # noqa: F401 — re-exported for backward-compatibility


def _extract_args(tc: dict) -> dict:
    """Extract tool arguments from a tool_call dict, handling both
    dict and JSON-string formats."""
    func = tc.get("function", {})
    if isinstance(func, dict):
        args = func.get("arguments", tc.get("arguments", tc.get("args", {})))
    else:
        args = tc.get("arguments", tc.get("args", {}))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return args if isinstance(args, dict) else {}


# ---------------------------------------------------------------------------
# ToolOrchestrator
# ---------------------------------------------------------------------------


class ToolOrchestrator:
    """Executes native tool_calls and manages the follow-up LLM conversation.

    The orchestrator owns:
    - Phase-1: looping through ``workflow.execute.*`` and ``primitive.*``
      tool_calls, executing them inline and collecting results.
    - Phase-2: building conversation history with tool results and calling
      the LLM for a natural-language follow-up response.
    """

    _WF_MAX_ITERATIONS = 50

    def __init__(
        self,
        workflow_engine: Any,
        workflow_store: Any,
        inline_tool_executor: Optional[Callable[[dict[str, Any]], dict[str, Any] | None]] = None,
        strategy_router: Any = None,
    ) -> None:
        self._workflow_engine = workflow_engine
        self._workflow_store = workflow_store
        self._inline_tool_executor = inline_tool_executor
        self._strategy_router = strategy_router

    def execute_tool_plan(
        self,
        tool_calls: list[dict],
        reply: str,
        agent_meta: Any,
        tool_context: dict[str, Any],
        conversation_history: list[dict],
        result: dict[str, Any],
        *,
        wf_max_iterations: int | None = None,
        user_request: str = "",
    ) -> str:
        """Execute *tool_calls* and run follow-up LLM if primitives executed.

        Args:
            tool_calls: The raw tool_calls from the routing result.
            reply: Current reply text (mutated with execution results).
            agent_meta: Agent metadata for LLM follow-up calls.
            tool_context: Tool definitions available to the LLM.
            conversation_history: Current conversation history.
            result: The original routing result dict (for output message).
            wf_max_iterations: Override for workflow max iterations.
            user_request: The original user message, carried through to the
                follow-up LLM so it doesn't lose context about *why* it
                executed the tools.

        Returns:
            Updated reply string incorporating tool execution results
            and optional follow-up LLM response.
        """
        max_iter = wf_max_iterations if wf_max_iterations is not None else self._WF_MAX_ITERATIONS
        executed_primitives: list[dict] = []

        # ── Phase 1: Execute tool calls ──────────────────────────────
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            func_name = (
                (tc.get("function", {}) if isinstance(tc.get("function"), dict) else {}).get("name", "")
                or tc.get("name", "")
            )

            if func_name.startswith("workflow.execute."):
                wf_id = func_name[len("workflow.execute."):]
                func = tc.get("function", {})
                if isinstance(func, dict):
                    args = func.get("arguments", tc.get("arguments", tc.get("args", {})))
                else:
                    args = tc.get("arguments", tc.get("args", {}))
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                context = {"args": args}
                try:
                    wf_state = self._workflow_engine.start_workflow(
                        wf_id, context=context,
                    )
                    wf_store = self._workflow_store
                    wf_store.save(wf_state)
                    iteration = 0
                    while iteration < max_iter:
                        iteration += 1
                        wf_state, outcome = self._workflow_engine.step(wf_state)
                        wf_store.save(wf_state)
                        if outcome.type == "continue":
                            continue
                        if outcome.type == "completed":
                            final_msg = (
                                wf_state.context.get("_workflow_result")
                                or wf_state.context.get("result")
                                or "Completed."
                            )
                            reply += f"\n\n[Executed workflow {wf_id!r}: {final_msg}]"
                            break
                        if outcome.type == "failed":
                            reply += f"\n\n[Workflow {wf_id!r} failed: {outcome.error}]"
                            break
                        if outcome.type == "waiting_for_input":
                            reply += f"\n\n[Workflow {wf_id!r} awaiting input: {outcome.prompt}]"
                            break
                        if outcome.type in ("llm_call", "planner_call"):
                            rendered = _render_context_templates(
                                outcome.config,
                                wf_state.context,
                                wf_state.step_results,
                            )
                            # Merge pattern_instructions (from apply_pattern step) into agent_metadata
                            if isinstance(rendered, dict):
                                pattern_instructions = rendered.pop("pattern_instructions", None)
                                if pattern_instructions:
                                    rendered.setdefault("agent_metadata", {})
                                    existing = rendered["agent_metadata"].get("patterns", [])
                                    rendered["agent_metadata"]["patterns"] = pattern_instructions + existing
                            from src.agent.strategy_router import RouterOutcome
                            ro = RouterOutcome(
                                type=outcome.type,
                                payload=dict(rendered) if isinstance(rendered, dict) else {},
                                step_id=outcome.step_id,
                            )
                            rr = self._strategy_router.route(ro)
                            if rr.get("error") is None:
                                wf_state, _ = self._workflow_engine.resume_with_result(
                                    wf_state, outcome.step_id, rr["output"],
                                )
                            else:
                                wf_state, _ = self._workflow_engine.fail_step(
                                    wf_state, outcome.step_id, rr["error"],
                                )
                            wf_store.save(wf_state)
                            continue
                        if outcome.type == "tool_execute":
                            if self._inline_tool_executor is not None:
                                try:
                                    inline_result = self._inline_tool_executor(outcome.config)
                                except Exception:
                                    inline_result = None
                                if inline_result is not None:
                                    wf_state, _ = self._workflow_engine.resume_with_result(
                                        wf_state, outcome.step_id, inline_result,
                                    )
                                    wf_store.save(wf_state)
                                    continue
                            reply += f"\n\n[Workflow {wf_id!r} deferred tool_execute]"
                            break
                        if outcome.type == "sub_workflow":
                            sub_id = outcome.workflow_id or ""
                            try:
                                wf_state = self._workflow_engine.start_workflow(
                                    sub_id, context=dict(wf_state.context),
                                )
                            except ValueError as exc:
                                wf_state, _ = self._workflow_engine.fail_step(
                                    wf_state, outcome.step_id, str(exc),
                                )
                            wf_store.save(wf_state)
                            continue
                    else:
                        reply += f"\n\n[Workflow {wf_id!r} exceeded iteration limit]"
                except ValueError as exc:
                    reply += f"\n\n[Workflow {wf_id!r} not found: {exc}]"

            elif func_name.startswith("primitive."):
                prim_name = func_name[len("primitive."):]
                func = tc.get("function", {})
                if isinstance(func, dict):
                    args = func.get("arguments", tc.get("arguments", tc.get("args", {})))
                else:
                    args = tc.get("arguments", tc.get("args", {}))
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                if self._inline_tool_executor is not None:
                    try:
                        prim_result = self._inline_tool_executor({
                            "skill_name": prim_name,
                            "arguments": args,
                        })
                    except Exception as exc:
                        prim_result = None
                        reply += f"\n\n[Primitive {prim_name!r} failed: {exc}]"
                    if prim_result is not None:
                        result_str = str(prim_result.get("data", prim_result.get("result", prim_result)))
                        if len(result_str) > 500:
                            result_str = result_str[:500] + "..."
                        executed_primitives.append({
                            "tool_call_id": tc.get("id", f"prim_{prim_name}"),
                            "name": prim_name,
                            "result_str": result_str,
                        })
                        reply += f"\n\n[Primitive {prim_name!r} \u2192 {result_str}]"
                    else:
                        reply += f"\n\n[Primitive {prim_name!r} returned no result]"
                else:
                    reply += f"\n\n[Primitive {prim_name!r} cannot execute (no inline executor)]"

        # ── Phase 2: Follow-up LLM calls for primitive results ────────
        # The follow-up LLM may request MORE tool calls (e.g. gmail_send
        # after gmail_read).  Loop with a bounded depth so multi-step
        # requests ("read X, analyze, and reply") complete fully.
        _DEFAULT_MAX_FOLLOW_UP_DEPTH = 3
        _follow_up_loop = 0
        while executed_primitives and self._strategy_router is not None:
            reply, fu_tool_calls = self._run_follow_up_llm(
                executed_primitives=executed_primitives,
                reply=reply,
                agent_meta=agent_meta,
                tool_context=tool_context,
                conversation_history=conversation_history,
                result=result,
                user_request=user_request,
            )
            if not fu_tool_calls:
                break  # LLM produced a text reply — work is done
            _follow_up_loop += 1
            if _follow_up_loop > _DEFAULT_MAX_FOLLOW_UP_DEPTH:
                reply += "\n\n[Tool execution depth limit reached]"
                break
            # Execute follow-up tool_calls and loop back to interpret results
            executed_primitives = []
            for tc in fu_tool_calls:
                if not isinstance(tc, dict):
                    continue
                func_name = (
                    (tc.get("function", {}) if isinstance(tc.get("function"), dict) else {}).get("name", "")
                    or tc.get("name", "")
                )
                if func_name.startswith("primitive."):
                    prim_name = func_name[len("primitive."):]
                    args = _extract_args(tc)
                    if self._inline_tool_executor is not None:
                        try:
                            prim_result = self._inline_tool_executor({
                                "skill_name": prim_name,
                                "arguments": args,
                            })
                        except Exception as exc:
                            prim_result = None
                            reply += f"\n\n[Primitive {prim_name!r} failed: {exc}]"
                        if prim_result is not None:
                            result_str = str(prim_result.get("data", prim_result.get("result", prim_result)))
                            if len(result_str) > 500:
                                result_str = result_str[:500] + "..."
                            executed_primitives.append({
                                "tool_call_id": tc.get("id", f"prim_{prim_name}"),
                                "name": prim_name,
                                "result_str": result_str,
                            })
                            reply += f"\n\n[Primitive {prim_name!r} \u2192 {result_str}]"
                        else:
                            reply += f"\n\n[Primitive {prim_name!r} returned no result]"
                    else:
                        reply += f"\n\n[Primitive {prim_name!r} cannot execute (no inline executor)]"
                else:
                    reply += f"\n\n[Unknown follow-up tool call: {func_name!r}]"
            # Update result's tool_calls so the next follow-up LLM knows
            # which tools were requested
            result = dict(result)
            result["tool_calls"] = fu_tool_calls

        return reply

    def _run_follow_up_llm(
        self,
        *,
        executed_primitives: list[dict],
        reply: str,
        agent_meta: Any,
        tool_context: dict[str, Any],
        conversation_history: list[dict],
        result: dict[str, Any],
        user_request: str = "",
    ) -> tuple[str, list[dict]]:
        """Build conversation history with tool results and call LLM for follow-up.
        
        Returns (reply, tool_calls) tuple.  tool_calls may be non-empty if the
        follow-up LLM chose additional tool invocations (e.g. gmail_send after
        reading an email).  Callers MUST process those tool_calls.
        """
        from src.agent.strategy_router import RouterOutcome

        orig_tool_calls = result.get("tool_calls", [])

        # Assistant message with tool_calls that LLM originally chose
        initial_text = result.get("output", {}).get("message", "")
        assistant_msg: dict[str, object] = {
            "role": "assistant",
            "content": initial_text if initial_text else None,
            "tool_calls": [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": (tc.get("function", {}) if isinstance(tc.get("function"), dict) else {}).get("name", "") or tc.get("name", ""),
                        "arguments": (tc.get("function", {}) if isinstance(tc.get("function"), dict) else {}).get("arguments", "") or tc.get("arguments", "{}"),
                    },
                }
                for tc in orig_tool_calls
                if any(
                    tc.get("id", "") == pe["tool_call_id"]
                    or pe["name"] in (
                        tc.get("function", {}) if isinstance(tc.get("function"), dict) else {}
                    ).get("name", "")
                    for pe in executed_primitives
                )
            ],
        }
        # Append directly to conversation_history so Phase 2 iterations
        # accumulate the full chain of tool calls and results.  Without this
        # the follow-up LLM cannot see what was already executed across
        # iterations and will re-request the same tools endlessly.
        conversation_history.append(assistant_msg)

        # Tool result messages
        for pe in executed_primitives:
            conversation_history.append({
                "role": "tool",
                "tool_call_id": pe["tool_call_id"],
                "content": pe["result_str"],
            })

        # Follow-up LLM call — include the user's original request so the
        # model remembers *why* the tools were executed and knows to
        # *complete* any remaining steps (e.g. sending the reply after
        # reading an email) rather than just summarising results.
        follow_up_prompt = (
            f"The user asked: \"{user_request}\"\n\n"
            "You are continuing to work on this request. "
            "Tool results are shown above.  Decide what to do next:\n"
            "- If you have all the information you need, complete the"
            " request now (produce your final response and take any"
            " remaining action such as drafting or sending).\n"
            "- If you still need more information or need to take"
            " another action, request more tool calls.\n"
            "Do NOT re-request a tool that has already produced results above."
        ) if user_request else "Based on the tool results, what's your response?"

        follow_up_outcome = RouterOutcome(
            type="llm_call",
            payload={
                "prompt": {
                    "message": follow_up_prompt,
                    "agent_id": agent_meta.identity.agent_id,
                    "agent_metadata": {
                        "name": agent_meta.identity.name,
                        "description": agent_meta.identity.description,
                        "persona": agent_meta.persona,
                        "tools": list(agent_meta.tools),
                        "workflows": list(agent_meta.workflows),
                    },
                },
                "backend": "conversational",
                "memory": {"conversation_history": conversation_history},
                "plan_context": {},
                "tool_context": tool_context,
            },
        )
        follow_up_result = self._strategy_router.route(follow_up_outcome)
        if follow_up_result.get("error") is None:
            fu_reply = follow_up_result["output"].get("message") or reply
            fu_tool_calls: list[dict] = follow_up_result.get("tool_calls", [])
            return fu_reply, fu_tool_calls
        # Keep the raw primitive reply as fallback
        return reply, []

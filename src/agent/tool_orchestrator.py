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


# ── Phase 2 helpers: tool result deduplication & large-output summarisation ─

_TOOL_OUTPUT_THRESHOLD: int = 10000
"""Character threshold above which a tool result is summarised.  Matches
the default in CompactionConfig.tool_output_threshold."""


def _summarize_large_output(result_str: str, tool_name: str) -> str:
    """Summarise a tool result that exceeds the output threshold.

    Extracts the first and last *threshold/10* characters plus a summary
    note, so the LLM retains the *what* and the *result* without the
    full verbatim content.
    """
    chunk_size = _TOOL_OUTPUT_THRESHOLD // 10
    first_chunk = result_str[:chunk_size]
    last_chunk = result_str[-chunk_size:] if len(result_str) > chunk_size else ""
    summary = (
        f"[SUMMARISED OUTPUT: {tool_name} — "
        f"{len(result_str)} chars, showing first/last {chunk_size} chars]\n"
        f"---first {chunk_size} chars---\n{first_chunk}\n"
    )
    if last_chunk:
        summary += f"---last {chunk_size} chars---\n{last_chunk}\n"
    return summary


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
        pattern_instructions: list[dict] | None = None,
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
            pattern_instructions: Optional pattern instruction dicts
                (``{pattern_id, name, instructions}``) to inject into
                follow-up LLM agent metadata so the model continues
                following pattern guidance (e.g. the ``plan_with_todo``
                iteration loop).

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
                        if outcome.type == "llm_call":
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
        #
        # Two-tier depth control:
        #   1. _MAX_STALL_ROUNDS (3) — break after N consecutive rounds
        #      with no *new* successful tool calls (progress-based reset).
        #      A round that produces at least one new successful call
        #      resets the stall counter.
        #   2. _MAX_TOTAL_ROUNDS (10) — hard ceiling that resets when a
        #      round produces successful *new* tool calls, so multi-step
        #      workflows ("plan → write → test → run") aren't cut short.
        #      The _MAX_STALL_ROUNDS guard still catches true runaway
        #      loops (LLM repeating the same failed calls).
        _MAX_TOTAL_ROUNDS = 10
        _MAX_STALL_ROUNDS = 3
        _follow_up_loop = 0
        _stall_rounds = 0
        _attempted_calls: set[tuple[str, str]] = set()  # (func_name, args_str) — all calls ever attempted
        while executed_primitives and self._strategy_router is not None:
            reply, fu_tool_calls = self._run_follow_up_llm(
                executed_primitives=executed_primitives,
                reply=reply,
                agent_meta=agent_meta,
                tool_context=tool_context,
                conversation_history=conversation_history,
                result=result,
                user_request=user_request,
                pattern_instructions=pattern_instructions,
            )
            if not fu_tool_calls:
                break  # LLM produced a text reply — work is done
            _follow_up_loop += 1
            if _follow_up_loop > _MAX_TOTAL_ROUNDS:
                reply += "\n\n[Tool execution depth limit reached]"
                break
            if _stall_rounds >= _MAX_STALL_ROUNDS:
                reply += (
                    f"\n\n[Tool execution halted — no new progress in"
                    f" {_MAX_STALL_ROUNDS} consecutive rounds]"
                )
                break
            # Execute follow-up tool_calls and loop back to interpret results
            executed_primitives = []
            _round_had_new_success = False
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
                    args_str = json.dumps(args, sort_keys=True)
                    call_sig = (func_name, args_str)
                    is_new_call = call_sig not in _attempted_calls
                    _attempted_calls.add(call_sig)
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
                            # Mark round as productive if this was a new
                            # call that succeeded (not an error)
                            if is_new_call and prim_result.get("status") != "error":
                                _round_had_new_success = True
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
            # Progress tracking: reset both counters when this round
            # produced at least one new successful tool call.
            # _follow_up_loop resets so multi-step workflows
            # (plan→write→test→run) don't hit the 10-round ceiling.
            # _stall_rounds still catches LLM repeating the same errors.
            if _round_had_new_success:
                _follow_up_loop = 0
                _stall_rounds = 0
            else:
                _stall_rounds += 1

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
        pattern_instructions: list[dict] | None = None,
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

        # Tool result messages (Phase 2: dedup + large-output summarisation)
        prev_tool_name: Optional[str] = None
        merged_content: List[str] = []
        for pe in executed_primitives:
            tool_name = pe.get("name", "")
            if tool_name and tool_name == prev_tool_name and merged_content:
                # Same tool called consecutively → merge into one result
                merged_content.append(pe["result_str"])
                continue

            # Flush any accumulated merged content before swapping to a new tool
            if merged_content:
                content = "\n\n---\n\n".join(merged_content) if len(merged_content) > 1 else merged_content[0]
                conversation_history.append({
                    "role": "tool",
                    "tool_call_id": merged_pe["tool_call_id"],  # first entry's call_id for the group
                    "content": _summarize_large_output(content, prev_tool_name) if len(content) > _TOOL_OUTPUT_THRESHOLD else content,
                })

            # Start new group
            prev_tool_name = tool_name
            merged_content = [pe["result_str"]]
            merged_pe = pe  # remember the last pe for call_id

        # Flush final group
        if merged_content:
            content = "\n\n---\n\n".join(merged_content) if len(merged_content) > 1 else merged_content[0]
            conversation_history.append({
                "role": "tool",
                "tool_call_id": merged_pe["tool_call_id"],  # first entry's call_id for the group
                "content": _summarize_large_output(content, prev_tool_name) if len(content) > _TOOL_OUTPUT_THRESHOLD else content,
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
            " another action, request more tool calls.\n\n"
            "IMPORTANT:\n"
            "- Do NOT re-request a tool that has already produced"
            " results above.  Use the results you already have.\n"
            "- If a tool returned an error (especially IntegrityError"
            " or UNIQUE constraint), assume the data already exists"
            " and proceed.  Do NOT retry the same operation.\n"
            "- When presenting a plan to the user, produce a text"
            " reply — do NOT loop on list/status tools.  The user"
            " will confirm the plan in their next message.\n"
            "- Each follow-up iteration is a fresh decision point."
            "  Default to completing the request with a text reply"
            " unless you genuinely need new information."
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
                        "patterns": pattern_instructions or [],
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

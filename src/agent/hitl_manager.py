"""
HITL (Human-in-the-Loop) confirmation manager.

Owns the lifecycle for side-effect tool call confirmation:
pending → confirmed → execute → done.

Extracted from supervisor.py per Sprint 18.2.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

from src.agent.contracts import AgentResponse
from src.agent.interfaces.agent_state import AgentState, LifecycleState
from src.agent.router import Route


class HitlManager:
    """Manages HITL confirmation for side-effect primitive tool_calls.

    The HITL manager owns:
    - Affirmative pattern matching (detecting user approval)
    - Side-effect tool call detection
    - Confirmed tool call execution
    - State transitions for the WAITING → ACTIVATED HITL cycle
    """

    _AFFIRMATIVE_RE: "re.Pattern[str]" = re.compile(
        r"^(?:\s*(?:yes|yeah|yep|sure|go ahead|proceed|confirm|do it"
        r"|send it|execute)\s*[,!.?]*)*\s*$",
        re.IGNORECASE,
    )

    _SIDE_EFFECT_ACTIONS: "frozenset[str]" = frozenset({
        "send", "delete", "forward", "create", "cancel",
        "archive", "move", "mark", "trash", "untrash", "modify",
        "update", "remove",
    })

    # Primitives whose side effects are purely local (e.g. todo DB writes)
    # and don't need HITL confirmation.  These are name-prefix matched
    # against the primitive name *after* stripping the "primitive." prefix.
    _SAFE_PRIMITIVE_PREFIXES: "frozenset[str]" = frozenset({
        "stdlib.todo.",
    })

    def __init__(
        self,
        inline_tool_executor: Optional[Callable[[dict[str, Any]], dict[str, Any] | None]] = None,
        strategy_router: Any = None,
    ) -> None:
        self._inline_tool_executor = inline_tool_executor
        self._strategy_router = strategy_router

    def is_affirmative(self, text: str) -> bool:
        """Check if user input is an affirmative confirmation."""
        return bool(self._AFFIRMATIVE_RE.fullmatch(text.strip()))

    @classmethod
    def has_side_effect_tool_calls(
        cls,
        tool_calls: list[dict],
    ) -> list[dict]:
        """Return side-effect ``primitive.*`` tool calls from *tool_calls*.

        Uses a name-based heuristic: if the primitive name (last dot-segment)
        starts with any action in ``_SIDE_EFFECT_ACTIONS``, it is
        classified as a side-effect operation.

        Primitives whose full name (after the ``primitive.`` prefix) starts
        with a prefix in ``_SAFE_PRIMITIVE_PREFIXES`` are excluded — they
        are safe, local-only operations (e.g. stdlib.todo.*).

        Returns the subset of calls that need confirmation.
        """
        side_effects = {
            "send", "delete", "forward", "draft", "create",
            "cancel", "archive", "move", "mark", "trash",
            "untrash", "modify", "update", "remove",
        }
        result: list[dict] = []
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            func_name = (
                (tc.get("function", {}) if isinstance(tc.get("function"), dict) else {}).get("name", "")
                or tc.get("name", "")
            )
            if not func_name.startswith("primitive."):
                continue
            prim_name = func_name[len("primitive."):]
            # Skip primitives that are safe (no HITL confirmation needed)
            if any(
                prim_name.startswith(p)
                for p in cls._SAFE_PRIMITIVE_PREFIXES
            ):
                continue
            # Extract the last segment for action heuristics
            last_segment = prim_name.rsplit(".", 1)[-1].lower()
            # Check if it starts with any side-effect word
            for action in side_effects:
                if last_segment.startswith(action):
                    result.append(tc)
                    break
        return result

    @staticmethod
    def describe_side_effect(tc: dict) -> str:
        """Return a human-readable description of a side-effect tool call."""
        func_name = (
            (tc.get("function", {}) if isinstance(tc.get("function"), dict) else {}).get("name", "")
            or tc.get("name", "")
        )
        # Strip the "primitive." prefix for readability
        display = func_name
        for prefix in ("primitive.", "mcp."):
            if display.startswith(prefix):
                display = display[len(prefix):]
                break
        return display

    def build_confirmation_prompt(self, side_effect_calls: list[dict]) -> str:
        """Build the HITL confirmation message for side-effect tool calls."""
        actions = sorted(set(
            self.describe_side_effect(c) for c in side_effect_calls
        ))
        return (
            "\n\n---\n"
            "\u26a1 **Confirmation required** \u2013 The assistant is about to"
            f" perform: **{', '.join(actions)}**.\n\n"
            "Reply **yes** to proceed, or **no** / revise your"
            " request to cancel."
        )

    def run_confirmed_skills(
        self,
        state: AgentState,
        pending: dict[str, Any],
        input_text: str,
        route: Route,
        meta: dict[str, Any],
        persist: Callable[[AgentState], AgentState],
        *,
        agent_meta: Any = None,
        tool_context: list[dict] | None = None,
        conversation_history: list[dict] | None = None,
        user_request: str = "",
        pattern_instructions: list[dict] | None = None,
    ) -> AgentState:
        """Execute or cancel pending primitive tool_calls based on user input.

        Called when the supervisor resumes from a WAITING state that
        was entered for HITL confirmation of side-effect ``primitive.*``
        tool_calls.

        * If the user affirms: run the pending tool_calls inline, then
          call a follow-up LLM to generate a natural-language response
          summarising what was done.
        * Otherwise: discard and return a cancellation message.
        """
        if self._AFFIRMATIVE_RE.fullmatch(input_text.strip()):
            tool_calls = pending.get("tool_calls", [])
            # Native tool_calls resume path
            reply = pending.get("original_reply", "")
            executed_primitives: list[dict] = []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    func_name = (
                        (tc.get("function", {}) if isinstance(tc.get("function"), dict) else {}).get("name", "")
                        or tc.get("name", "")
                    )
                    if func_name.startswith("primitive."):
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
                                reply += f"\n\n[Primitive {prim_name!r} failed: {exc}]"
                                continue
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

            # ── Run follow-up LLM to generate a natural-language response ──
            if executed_primitives and self._strategy_router is not None and agent_meta is not None:
                fu_reply = self._run_hitl_follow_up_llm(
                    executed_primitives=executed_primitives,
                    reply=reply,
                    agent_meta=agent_meta,
                    tool_context=tool_context or [],
                    conversation_history=list(conversation_history or []),
                    user_request=user_request,
                    tool_calls=tool_calls,
                    pattern_instructions=pattern_instructions,
                )
                if fu_reply:
                    reply = fu_reply

            metadata: dict[str, Any] = {
                "correlation_id": state.correlation_id,
                "trace_id": state.trace_id,
                "agent_id": state.agent_id,
                "confidence": route.confidence,
                "route_destination": route.destination,
            }
            return persist(state.with_(
                lifecycle_state=LifecycleState.ACTIVATED,
                route_result=route,
                final_response=AgentResponse(
                    reply=reply, metadata=metadata,
                ),
                supervisor_metadata=meta,
                _reason="User confirmed \u2014 executing pending tool_calls",
            ))
        # User declined or gave unexpected input \u2192 cancel
        metadata = {
            "correlation_id": state.correlation_id,
            "trace_id": state.trace_id,
            "agent_id": state.agent_id,
            "confidence": route.confidence,
            "route_destination": route.destination,
        }
        return persist(state.with_(
            lifecycle_state=LifecycleState.ACTIVATED,
            route_result=route,
            final_response=AgentResponse(
                reply=(
                    "The action was cancelled based on your response."
                ),
                metadata=metadata,
            ),
            supervisor_metadata=meta,
            _reason="User declined \u2014 pending tool_calls cancelled",
        ))

    def _run_hitl_follow_up_llm(
        self,
        *,
        executed_primitives: list[dict],
        reply: str,
        agent_meta: Any,
        tool_context: list[dict],
        conversation_history: list[dict],
        user_request: str,
        tool_calls: list[dict],
        pattern_instructions: list[dict] | None = None,
    ) -> str | None:
        """Call the LLM to generate a natural-language response after
        HITL-confirmed tool execution.

        Returns the LLM's follow-up reply, or ``None`` if the LLM call
        failed (callers should fall back to the raw reply).
        """
        from src.agent.strategy_router import RouterOutcome

        # Build assistant message with the tool_calls that were executed
        assistant_msg: dict[str, object] = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": (
                            (tc.get("function", {})
                             if isinstance(tc.get("function"), dict)
                             else {}).get("name", "")
                            or tc.get("name", "")
                        ),
                        "arguments": (
                            (tc.get("function", {})
                             if isinstance(tc.get("function"), dict)
                             else {}).get("arguments", "")
                            or tc.get("arguments", "{}")
                        ),
                    },
                }
                for tc in tool_calls
            ],
        }
        conversation_history.append(assistant_msg)

        # Append tool result messages
        for pe in executed_primitives:
            conversation_history.append({
                "role": "tool",
                "tool_call_id": pe["tool_call_id"],
                "content": pe["result_str"],
            })

        follow_up_prompt = (
            f"The user asked: \"{user_request}\"\n\n"
            "You executed tool calls, and the results are shown above. "
            "The user confirmed this action. "
            "Summarize what was done in a natural, helpful tone. "
            "Do NOT re-request any tools \u2014 the work is done."
            " Produce a text reply only."
        ) if user_request else (
            "Based on the tool results shown above, what's your response? "
            "The user confirmed this action. "
            "Summarize what was done in a natural, helpful tone."
            " Produce a text reply only."
        )

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
            fu_reply = follow_up_result["output"].get("message")
            if fu_reply:
                return fu_reply
        return None

"""
Sessioned Adapter
=================

Wraps a :class:`GatewayAgentAdapter` with automatic per-session conversation
history management.

Sessions are keyed by ``channel:user_id`` so that returning users via any
transport (CLI, Web, Slack, WebSocket, …) automatically pick up where they
left off.

No changes to individual entry points are required — wire once at the
composition root and every channel gets multi-turn memory for free.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List

from src.gateway.adapters.agent_adapter import AgentRequest, GatewayAgentAdapter

# Maximum number of turns (user+assistant pairs) retained per session.
# Beyond this, oldest turns are evicted to prevent unbounded context growth.
_MAX_HISTORY_TURNS = 25


class SessionedAdapter:
    """GatewayAgentAdapter wrapper with automatic session management.

    On each ``ingest()``:

    1. Look up or create a conversation history for the session.
    2. Inject ``conversation_history`` into the request metadata.
    3. Delegate to the inner adapter.
    4. On success, append the user + assistant turns to the session.

    Tool calls from LLM responses are preserved in assistant entries so that
    the LLM sees evidence of past tool usage on subsequent turns, preventing
    the "tool forgetting" bug.
    """

    def __init__(self, inner: GatewayAgentAdapter) -> None:
        self._inner = inner
        # {session_key: [{"role": "user"/"assistant", "content": str}, ...]}
        self._sessions: dict[str, List[dict[str, Any]]] = {}
        # Track the last ingest session key so resume() uses a consistent key.
        self._last_session_key: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(self, request: AgentRequest) -> Dict[str, Any]:
        """Send a request through the session-managed pipeline."""
        key = self._session_key(request)
        self._last_session_key = key
        history = list(self._sessions.get(key, []))

        # Inject session history into a copy of the request
        enriched = dataclasses.replace(
            request,
            metadata={**request.metadata, "conversation_history": history},
        )

        result = self._inner.ingest(enriched)

        # Capture successful turns into session history.
        # NOTE: Create a *new* list rather than mutating ``history`` —
        # the same list reference was passed through the adapter pipeline
        # and is stored in ``PromptRequest.memory.conversation_history``.
        # Mutating it in-place would retroactively change the captured
        # request, breaking tests that inspect ``last_request`` after
        # the call returns.
        if isinstance(result, dict) and "reply" in result:
            self._sessions[key] = self._build_history(
                history,
                request.message_text,
                result["reply"],
                result.get("metadata", {}),
            )

        return result

    def resume(self, agent_id: str, message_text: str) -> Dict[str, Any]:
        """Resume a WAITING agent, returning the same shape as ``ingest()``.

        1. Load session history for the last-ingest session key.
        2. Inject it as ``conversation_history`` into the inner adapter
           so the LLM sees the full multi-turn context on resume.
        3. On success (reply in the result) the new turn is appended
           to the session history.
        """
        key = self._last_session_key or f"cli:{agent_id}"
        history = list(self._sessions.get(key, []))
        result = self._inner.resume(
            agent_id, message_text,
            conversation_history=history,
        )

        # Capture successful turns into session history.
        if isinstance(result, dict) and "reply" in result:
            key = self._last_session_key or f"cli:{agent_id}"
            history = list(self._sessions.get(key, []))
            self._sessions[key] = self._build_history(
                history,
                message_text,
                result["reply"],
                result.get("metadata", {}),
            )

        return result

    # ------------------------------------------------------------------
    # Session management helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_annotations(text: str) -> str:
        """Remove ``[Primitive '...' → ...]`` / ``[Workflow '...' → ...]`` annotations.

        These annotations are useful in the **display** reply (the user sees
        what happened), but when stored in conversation history they leak
        raw tool errors and internal state that confuses the LLM on future
        turns.
        """
        result: list[str] = []
        i = 0
        while i < len(text):
            if text[i] == "[" and (
                text[i : i + 10] == "[Primitive "
                or text[i : i + 9] == "[Workflow "
            ):
                # Find the matching closing bracket (bracket-depth aware)
                depth = 0
                for j in range(i, len(text)):
                    if text[j] == "[":
                        depth += 1
                    elif text[j] == "]":
                        depth -= 1
                        if depth == 0:
                            # j points at the closing ] — skip past it
                            i = j + 1
                            break
                else:
                    # No matching bracket found — stop scanning
                    i = len(text)

                # Skip trailing whitespace/newline
                while i < len(text) and text[i] in " \t\n\r":
                    i += 1
            else:
                result.append(text[i])
                i += 1
        return "".join(result)

    def _build_history(
        self,
        prior: List[dict],
        user_msg: str,
        assistant_reply: str,
        metadata: dict,
    ) -> List[dict]:
        """Append a user+assistant turn and enforce the turn limit.

        Assistant entries include tool-call metadata when available so the
        LLM sees evidence of past tool usage on subsequent turns.
        """
        assistant_entry: dict[str, Any] = {
            "role": "assistant",
            "content": self._strip_annotations(assistant_reply),
        }

        # Preserve tool-call evidence in session history.
        # The supervisor injects ``llm_tool_calls`` into the result metadata
        # when the LLM's response included tool calls.
        llm_tool_calls = metadata.get("llm_tool_calls")
        if llm_tool_calls:
            assistant_entry["tool_calls"] = llm_tool_calls

        turns = prior + [
            {"role": "user", "content": user_msg},
            assistant_entry,
        ]

        # Enforce maximum turn limit — evict oldest pairs.
        if len(turns) > _MAX_HISTORY_TURNS * 2:
            excess = len(turns) - _MAX_HISTORY_TURNS * 2
            turns = turns[excess:]

        return turns

    @staticmethod
    def _session_key(request: AgentRequest) -> str:
        """Derive a session key from a request.

        Unidentified users (no ``user_id``) are grouped under ``"anon"``
        so that the CLI default path gets a session.
        """
        user_part = request.user_id or "anon"
        return f"{request.channel}:{user_part}"

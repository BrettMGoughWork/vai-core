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
from typing import Any, Dict

from src.gateway.adapters.agent_adapter import AgentRequest, GatewayAgentAdapter


class SessionedAdapter:
    """GatewayAgentAdapter wrapper with automatic session management.

    On each ``ingest()``:

    1. Look up or create a conversation history for the session.
    2. Inject ``conversation_history`` into the request metadata.
    3. Delegate to the inner adapter.
    4. On success, append the user + assistant turns to the session.
    """

    def __init__(self, inner: GatewayAgentAdapter) -> None:
        self._inner = inner
        # {session_key: [{"role": "user"/"assistant", "content": str}, ...]}
        self._sessions: dict[str, list[dict[str, str]]] = {}
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
            self._sessions[key] = history + [
                {"role": "user", "content": request.message_text},
                {"role": "assistant", "content": result["reply"]},
            ]

        return result

    def resume(self, agent_id: str, message_text: str) -> Dict[str, Any]:
        """Resume a WAITING agent, returning the same shape as ``ingest()``.

        Delegates to the inner adapter's ``resume()``.  On success (reply in
        the result) the turn is appended to the session history.
        """
        result = self._inner.resume(agent_id, message_text)

        # Capture successful turns into session history.
        if isinstance(result, dict) and "reply" in result:
            key = self._last_session_key or f"cli:{agent_id}"
            history = list(self._sessions.get(key, []))
            self._sessions[key] = history + [
                {"role": "user", "content": message_text},
                {"role": "assistant", "content": result["reply"]},
            ]

        return result

    # ------------------------------------------------------------------
    # Session management helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _session_key(request: AgentRequest) -> str:
        """Derive a session key from a request.

        Unidentified users (no ``user_id``) are grouped under ``"anon"``
        so that the CLI default path gets a session.
        """
        user_part = request.user_id or "anon"
        return f"{request.channel}:{user_part}"

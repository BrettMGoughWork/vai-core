"""
S5-side Gateway Adapter
========================

Concrete implementation of the ``GatewayAgentAdapter`` protocol that
wires a :class:`~src.agent.supervisor.Supervisor` instance.

Flow
----
1. Create a new agent instance via ``Supervisor.create_agent()``
2. Wrap the request as an ``AgentMessage`` and activate via
   ``Supervisor.activate_agent()``
3. Run one agent step via ``Supervisor.run_agent_step()``
4. Return the response (or pending / error state)
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

from src.agent.contracts import AgentMessage
from src.agent.interfaces.agent_state import LifecycleState
from src.agent.supervisor import Supervisor
from src.gateway.adapters.agent_adapter import AgentRequest, GatewayAgentAdapter

# Default agent id used when no explicit agent routing is available.
_DEFAULT_AGENT_ID = "default-agent"


class AgentGatewayAdapter:
    """Concrete adapter: Gateway → S5 Supervisor.

    The adapter owns a :class:`Supervisor` instance and exposes
    ``ingest()`` so the Gateway can hand off channel input without
    importing any S5 internals.
    """

    def __init__(self, supervisor: Supervisor) -> None:
        self._supervisor = supervisor

    def ingest(self, request: AgentRequest) -> Dict[str, Any]:
        """Process channel input through the S5 Supervisor.

        Args:
            request: The normalised channel request.

        Returns:
            A dict with one of these shapes:

            - Success:  ``{"reply": str, "metadata": dict}``
            - Pending:  ``{"state": "waiting", "agent_id": str}``
            - Error:    ``{"error": str}``
        """
        agent_id = (
            request.metadata.get("agent_id")
            if request.metadata
            else None
        ) or _DEFAULT_AGENT_ID

        # 1. Create agent runtime state
        try:
            state = self._supervisor.create_agent(agent_id)
        except Exception as exc:
            return {"error": f"Failed to create agent: {exc}"}

        # 2. Wrap as AgentMessage and activate
        msg = AgentMessage(
            message=request.message_text,
            context={
                "channel": request.channel,
                "user_id": request.user_id,
                **request.metadata,
            },
        )
        try:
            state = self._supervisor.activate_agent(
                state, msg, channel=request.channel,
            )
        except Exception as exc:
            return {"error": f"Failed to activate agent: {exc}"}

        # 3. Run one agent step
        try:
            state = self._supervisor.run_agent_step(state)
        except Exception as exc:
            return {"error": f"Agent step failed: {exc}"}

        # 4. Interpret outcome
        if state.lifecycle_state in (
            LifecycleState.COMPLETED,
            LifecycleState.FAILED,
        ):
            resp = self._supervisor.get_response(state)
            if resp is not None and resp.reply is not None:
                return {
                    "reply": resp.reply,
                    "metadata": resp.metadata,
                    "agent_id": agent_id,
                }
            return {
                "error": (
                    "Agent completed without producing a response"
                    if state.lifecycle_state == LifecycleState.COMPLETED
                    else state._reason or "Agent failed"
                ),
            }

        # Agent is WAITING (jobs dispatched to S4B) or RUNNING
        return {
            "state": state.lifecycle_state.value,
            "agent_id": agent_id,
        }

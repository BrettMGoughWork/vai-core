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
        # Extract conversation_history from metadata (injected by
        # submit_channel_input) so the interactive CLI loop can preserve
        # multi-turn context across fresh agent instances.
        conversation_history = (
            request.metadata.pop("conversation_history", [])
            if request.metadata else []
        )
        try:
            state = self._supervisor.activate_agent(
                state, msg, channel=request.channel,
                conversation_history=conversation_history,
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
            # Derive failure reason from lifecycle history or errors
            last_event = state.lifecycle_history[-1] if state.lifecycle_history else None
            reason = last_event.reason if last_event else ""
            if not reason and state.errors:
                reason = state.errors[-1].get("message", "")
            return {
                "error": (
                    "Agent completed without producing a response"
                    if state.lifecycle_state == LifecycleState.COMPLETED
                    else reason or "Agent failed"
                ),
            }

        # Agent is WAITING (jobs dispatched to S4B) or RUNNING
        result: Dict[str, Any] = {
            "state": state.lifecycle_state.value,
            "agent_id": agent_id,
        }
        # Surface interaction prompt/schema for WAITING workflows
        meta = state.supervisor_metadata
        if meta.get("workflow_waiting_for") == "user_input":
            result["prompt"] = meta.get("workflow_interaction_prompt", "")
            result["request_id"] = meta.get("workflow_interaction_request_id", "")
            schema = meta.get("workflow_interaction_schema")
            if schema:
                result["input_schema"] = schema
        # Surface confirmation prompt for primitive HITL gate
        elif meta.get("waiting_for") == "tool_confirmation":
            resp = self._supervisor.get_response(state)
            if resp is not None and resp.reply is not None:
                result["prompt"] = resp.reply
        return result

    def resume(self, agent_id: str, message_text: str) -> Dict[str, Any]:
        """Resume a WAITING agent with new input.

        Loads the agent's state from the store, runs one step with the
        given message, and returns the result in the same shape as
        ``ingest()``.

        Args:
            agent_id:     The WAITING agent to resume.
            message_text: Input text to resume the workflow with.

        Returns:
            Same shape as ``ingest()`` — one of:

            - Success:  ``{"reply": str, "metadata": dict, "agent_id": str}``
            - Pending:  ``{"state": "waiting", "agent_id": str}``
            - Error:    ``{"error": str}``
        """
        try:
            state = self._supervisor.get_agent_state(agent_id)
        except Exception as exc:
            return {"error": f"Failed to load agent state: {exc}"}

        if state.lifecycle_state.value == "waiting":
            # Transition from WAITING — no activation needed
            try:
                state = self._supervisor.run_agent_step(
                    state, message=message_text,
                )
            except Exception as exc:
                return {"error": f"Resume step failed: {exc}"}

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

            # Still waiting (multi-step resume) or running
            result: Dict[str, Any] = {
                "state": state.lifecycle_state.value,
                "agent_id": agent_id,
            }
            # Surface interaction prompt/schema for multi-step resumes
            meta = state.supervisor_metadata
            if meta.get("workflow_waiting_for") == "user_input":
                result["prompt"] = meta.get("workflow_interaction_prompt", "")
                result["request_id"] = meta.get("workflow_interaction_request_id", "")
                schema = meta.get("workflow_interaction_schema")
                if schema:
                    result["input_schema"] = schema
            # Surface confirmation prompt for primitive HITL gate
            elif meta.get("waiting_for") == "tool_confirmation":
                resp = self._supervisor.get_response(state)
                if resp is not None and resp.reply is not None:
                    result["prompt"] = resp.reply
            return result

        return {"error": f"Agent {agent_id!r} is not WAITING"}

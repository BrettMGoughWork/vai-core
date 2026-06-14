"""
Phase 5.5 — Agent Runtime Supervisor
======================================

The supervisor is the **top-level agent execution orchestrator**.  It owns
the full lifecycle of an agent instance — creation, activation, message
routing, job dispatch, suspension, cancellation, and completion.

S5.5 does **not**:
- call LLMs
- execute tools
- invoke skills
- perform cognitive reasoning
- mutate S4 state
- define new execution semantics

S5.5 coordinates the Agent Router (S5.2) and the job interface (S5.4) to
route incoming messages to the appropriate destination: Runtime (LLM
conversation), S6 (workflow orchestration), or S4B (capability execution).

Public API
----------
- ``create_agent``  — instantiate runtime state for a registered agent
- ``activate_agent`` — delegate to S5.2 to build activation context
- ``run_agent_step`` — route message -> dispatch to Runtime/S6/S4B
- ``suspend_agent`` — pause agent execution (timeout / external signal)
- ``resume_agent`` — restore a suspended agent to RUNNING
- ``cancel_agent`` — terminate agent execution (manual or system)
- ``complete_agent`` — mark agent as completed with a final response
- ``get_response`` — retrieve the final AgentResponse (if any)
- ``get_lifecycle_history`` — full audit trail of lifecycle events
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from src.agent.activation import (
    ActivatedAgentContext,
    activate_agent as s52_activate_agent,
)
from src.agent.contracts import AgentMessage, AgentResponse
from src.agent.interfaces.agent_state import (
    AgentState,
    LifecycleEvent,
    LifecycleState,
)
from src.agent.interfaces.agent_state_store import AgentStateStore
from src.agent.job_interface import JobDispatchResult, dispatch_route
from src.agent.registry import AgentRegistry, AgentNotFoundError
from src.agent.router import DEST_RUNTIME, DEST_S4B, DEST_S6, Route, route_message
from src.runtime.interfaces import (
    PromptRequest,
    PromptResponse,
    S1Error,
    call_runtime_backend,
)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SupervisorError(Exception):
    """Base error for supervisor operations."""


class AgentNotActiveError(SupervisorError):
    """Raised when an operation requires an active agent."""


class AgentInTerminalStateError(SupervisorError):
    """Raised when attempting to transition from a terminal state."""


class AgentNotSuspendedError(SupervisorError):
    """Raised when attempting to resume a non-suspended agent."""


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------


class Supervisor:
    """Agent Runtime Supervisor — manages agent lifecycle and execution.

    The supervisor is instantiated with the dependencies it needs
    (registry, optional skill runner, optional submit-job callable) and
    exposes stateless, deterministic lifecycle methods.

    All public methods return (new ``AgentState``, optional result).
    """

    def __init__(
        self,
        registry: AgentRegistry,
        store: AgentStateStore,
        *,
        submit_job_callable: Optional[Callable[[Any], str]] = None,
        auto_persist: bool = True,
    ) -> None:
        self._registry = registry
        self._store = store
        self._submit_job = submit_job_callable
        self._auto_persist = auto_persist

    # ── 1. create_agent ────────────────────────────────────────────────

    def create_agent(self, agent_id: str) -> AgentState:
        """Create runtime state for a registered agent.

        Args:
            agent_id: Must be registered in the agent registry.

        Returns:
            A new ``AgentState`` in ``CREATED`` state.

        Raises:
            SupervisorError: If the agent_id is not registered.
        """
        if not agent_id:
            raise SupervisorError("agent_id must be non-empty")

        try:
            metadata = self._registry.get_agent(agent_id)
        except AgentNotFoundError:
            raise SupervisorError(
                f"cannot create runtime state for unknown agent {agent_id!r}"
            )

        now = datetime.now(timezone.utc).isoformat()
        return self._persist(AgentState(
            agent_id=agent_id,
            lifecycle_state=LifecycleState.CREATED,
            timestamps={"created_at": now},
            correlation_id=str(uuid.uuid4()),
            trace_id=str(uuid.uuid4()),
            supervisor_metadata={
                "timeout_ms": metadata.constraints.timeout_ms,
                "total_routes": 0,
            },
            lifecycle_history=[
                LifecycleEvent(
                    timestamp=now,
                    from_state=None,
                    to_state=LifecycleState.CREATED,
                    reason=f"Agent runtime state created for {agent_id!r}",
                ),
            ],
        ))

    # ── 2. activate_agent ──────────────────────────────────────────────

    def activate_agent(
        self,
        state: AgentState,
        message: AgentMessage,
        *,
        channel: str = "cli",
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        routing_hints: Optional[Dict[str, Any]] = None,
        channel_metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentState:
        """Activate an agent — delegates to S5.2 ``activate_agent()``.

        The agent must be in ``CREATED`` state.  After activation the
        state transitions to ``ACTIVATED`` and the activation snapshot
        is stored.

        Args:
            state: Current agent state (must be CREATED).
            message: Inbound user or system message.
            channel: Originating channel.
            correlation_id: Override correlation ID (defaults to state's).
            trace_id: Override trace ID (defaults to state's).

        Returns:
            Updated ``AgentState`` in ``ACTIVATED`` state.

        Raises:
            AgentInTerminalStateError: If state is terminal.
            SupervisorError: If activation fails.
        """
        self._require_not_terminal(state)

        try:
            ctx = s52_activate_agent(
                agent_id=state.agent_id,
                message=message,
                registry=self._registry,
                channel=channel,
                correlation_id=correlation_id or state.correlation_id,
                trace_id=trace_id or state.trace_id,
                conversation_history=conversation_history,
                routing_hints=routing_hints,
                channel_metadata=channel_metadata,
            )
        except Exception as exc:
            raise SupervisorError(
                f"S5.2 activation failed for agent {state.agent_id!r}: {exc}"
            ) from exc

        state_updates: Dict[str, Any] = {
            "lifecycle_state": LifecycleState.ACTIVATED,
            "activation_snapshot": ctx,
            "_reason": f"Agent activated via {channel} channel",
            "_details": {"channel": channel},
        }
        if correlation_id:
            state_updates["correlation_id"] = correlation_id
        if trace_id:
            state_updates["trace_id"] = trace_id
        return self._persist(state.with_(**state_updates))

    # ── 3. run_agent_step ──────────────────────────────────────────────

    def run_agent_step(
        self,
        state: AgentState,
        *,
        message: Optional[str] = None,
    ) -> AgentState:
        """Execute one agent iteration: route -> dispatch.

        1. Transition to RUNNING
        2. Route the message via ``route_message()`` (S5.2)
        3. Based on destination:
           - ``DEST_RUNTIME``  → call LLM backend → produce AgentResponse
           - ``DEST_S6``      → mark as WAITING (workflow dispatch TBD)
           - ``DEST_S4B``     → dispatch jobs via ``dispatch_route()`` → WAITING
        4. Return updated state

        Args:
            state: Current agent state (must be ACTIVATED or RUNNING/WAITING
                   for continuation).
            message: Incoming message text to route.

        Returns:
            Updated ``AgentState`` with the result of this step.

        Raises:
            AgentNotActiveError: If agent is not in an active state.
            AgentInTerminalStateError: If state is terminal.
        """
        if state.is_terminal():
            raise AgentInTerminalStateError(
                f"cannot run step on terminal agent {state.agent_id!r} "
                f"(state={state.lifecycle_state.value})"
            )

        if state.lifecycle_state not in (
            LifecycleState.ACTIVATED,
            LifecycleState.RUNNING,
            LifecycleState.WAITING,
        ):
            raise AgentNotActiveError(
                f"cannot run step on agent {state.agent_id!r} in "
                f"state {state.lifecycle_state.value}; "
                f"expected ACTIVATED, RUNNING, or WAITING"
            )

        # 1. Transition to RUNNING
        state = state.with_(
            lifecycle_state=LifecycleState.RUNNING,
            _reason="Agent step started",
        )

        # 2. Ensure we have an activation snapshot
        ctx = state.activation_snapshot
        if ctx is None:
            return self._persist(state.with_(
                lifecycle_state=LifecycleState.FAILED,
                errors=state.errors + [
                    {
                        "type": "missing_activation",
                        "message": (
                            "run_agent_step called without activation snapshot"
                        ),
                    }
                ],
                _reason="Missing activation snapshot — cannot run agent step",
            ))

        # 3. Route the message
        input_text = message or ctx.envelope.message.message
        route = route_message(
            message=input_text,
            agent=ctx.context.agent_metadata,
        )

        # 4. Dispatch based on destination
        new_errors = list(state.errors)
        meta = dict(state.supervisor_metadata)
        meta["total_routes"] = meta.get("total_routes", 0) + 1

        if route.destination == DEST_RUNTIME:
            # LLM conversation path — call Runtime backend
            agent_meta = ctx.context.agent_metadata
            runtime_request = PromptRequest(
                prompt={
                    "message": input_text,
                    "agent_id": agent_meta.identity.agent_id,
                    "agent_metadata": {
                        "name": agent_meta.identity.name,
                        "description": agent_meta.identity.description,
                    },
                },
                memory={},
                plan_context={},
                tool_context=[],
            )

            runtime_response = call_runtime_backend(
                runtime_request, backend="conversational"
            )

            if isinstance(runtime_response, PromptResponse):
                reply = runtime_response.output.get(
                    "message", "I'm not sure how to respond."
                )
                return self._persist(state.with_(
                    lifecycle_state=LifecycleState.COMPLETED,
                    route_result=route,
                    final_response=AgentResponse(
                        reply=reply,
                        metadata={
                            "correlation_id": state.correlation_id,
                            "trace_id": state.trace_id,
                            "agent_id": state.agent_id,
                            "confidence": route.confidence,
                            "route_destination": route.destination,
                        },
                    ),
                    supervisor_metadata=meta,
                    _reason="Agent produced conversational response via Runtime route",
                    _details={
                        "confidence": route.confidence,
                        "route_destination": route.destination,
                    },
                ))

            # S1Error — fall back to mock backend
            fallback = call_runtime_backend(runtime_request, backend="mock")
            fallback_reply = "I'm not sure how to respond."
            if isinstance(fallback, PromptResponse):
                fallback_reply = fallback.output.get("message", fallback_reply)
            else:
                fallback_reply = (
                    f"[Runtime unavailable: {runtime_response.message}]"
                )

            return self._persist(state.with_(
                lifecycle_state=LifecycleState.COMPLETED,
                route_result=route,
                final_response=AgentResponse(
                    reply=fallback_reply,
                    metadata={
                        "correlation_id": state.correlation_id,
                        "trace_id": state.trace_id,
                        "agent_id": state.agent_id,
                        "confidence": route.confidence,
                        "route_destination": route.destination,
                        "runtime_fallback": True,
                        "runtime_error": runtime_response.message,
                    },
                ),
                supervisor_metadata=meta,
                _reason="Agent produced conversational response via mock fallback",
                _details={
                    "confidence": route.confidence,
                    "route_destination": route.destination,
                    "runtime_fallback": True,
                },
            ))

        if route.destination == DEST_S4B:
            # Capability execution path — dispatch jobs
            dispatch_result = dispatch_route(
                route=route,
                submit_job_callable=self._submit_job,
            )
            has_dispatched = len(dispatch_result.dispatched_jobs) > 0

            if dispatch_result.errors:
                for job_id, err_msg in dispatch_result.errors:
                    new_errors.append({
                        "type": "dispatch_error",
                        "job_id": job_id,
                        "message": err_msg,
                    })

            if has_dispatched:
                return self._persist(state.with_(
                    lifecycle_state=LifecycleState.WAITING,
                    route_result=route,
                    dispatch_result=dispatch_result,
                    errors=new_errors,
                    supervisor_metadata=meta,
                    _reason=f"Dispatched {len(dispatch_result.dispatched_jobs)} jobs — awaiting results",
                    _details={
                        "dispatched_count": len(dispatch_result.dispatched_jobs),
                    },
                ))

            # No jobs dispatched — fall through to completed
            new_errors.append({
                "type": "dispatch_empty",
                "message": "Route matched S4B but no jobs were dispatched",
            })

        if route.destination == DEST_S6:
            # Workflow execution path — not yet implemented
            return self._persist(state.with_(
                lifecycle_state=LifecycleState.WAITING,
                route_result=route,
                errors=new_errors,
                supervisor_metadata=meta,
                _reason="Workflow dispatch not yet implemented (DEST_S6)",
                _details={"route_destination": route.destination},
            ))

        # Fallback: completed with no output
        return self._persist(state.with_(
            lifecycle_state=LifecycleState.COMPLETED,
            route_result=route,
            final_response=AgentResponse(
                reply="Agent completed without producing output.",
                metadata={
                    "correlation_id": state.correlation_id,
                    "trace_id": state.trace_id,
                    "agent_id": state.agent_id,
                },
            ),
            errors=new_errors,
            supervisor_metadata=meta,
            _reason="Agent step completed with no action intents",
        ))

    # ── 4. suspend_agent ───────────────────────────────────────────────

    def suspend_agent(
        self,
        state: AgentState,
        reason: str,
        *,
        details: Optional[Dict[str, Any]] = None,
    ) -> AgentState:
        """Suspend an active agent (pause execution).

        Valid transitions:
        - RUNNING -> SUSPENDED
        - WAITING -> SUSPENDED

        The supervisor records the suspension reason and preserves the
        current state snapshot for future resumption.

        Args:
            state: Current agent state (must be active).
            reason: Human-readable reason for suspension.
            details: Optional structured details.

        Returns:
            Updated ``AgentState`` in ``SUSPENDED`` state.

        Raises:
            AgentNotActiveError: If agent is not in an active state.
            AgentInTerminalStateError: If state is terminal.
        """
        self._require_not_terminal(state)

        if not state.is_active():
            raise AgentNotActiveError(
                f"cannot suspend agent {state.agent_id!r} in "
                f"state {state.lifecycle_state.value}; "
                f"expected RUNNING or WAITING"
            )

        return self._persist(state.with_(
            lifecycle_state=LifecycleState.SUSPENDED,
            _reason=reason,
            _details=details or {},
        ))

    # ── 5. resume_agent ────────────────────────────────────────────────

    def resume_agent(self, state: AgentState) -> AgentState:
        """Resume a suspended agent back to RUNNING.

        Only valid from SUSPENDED state.  The supervisor restores the
        agent to RUNNING so the next ``run_agent_step()`` can continue.

        Args:
            state: Current agent state (must be SUSPENDED).

        Returns:
            Updated ``AgentState`` in ``RUNNING`` state.

        Raises:
            AgentNotSuspendedError: If agent is not in SUSPENDED state.
            AgentInTerminalStateError: If state is terminal.
        """
        self._require_not_terminal(state)

        if state.lifecycle_state != LifecycleState.SUSPENDED:
            raise AgentNotSuspendedError(
                f"cannot resume agent {state.agent_id!r} from "
                f"state {state.lifecycle_state.value}; "
                f"expected SUSPENDED"
            )

        return self._persist(state.with_(
            lifecycle_state=LifecycleState.RUNNING,
            _reason="Agent resumed from suspension",
            _details={
                "suspended_duration_ms": self._compute_duration_ms(
                    state.timestamps.get("suspended_at", ""),
                ),
            },
        ))

    # ── 6. cancel_agent ────────────────────────────────────────────────

    def cancel_agent(
        self,
        state: AgentState,
        reason: str,
        *,
        details: Optional[Dict[str, Any]] = None,
    ) -> AgentState:
        """Cancel an active agent (terminate execution).

        Valid from any non-terminal state.  Transitions to FAILED.

        The supervisor records the cancellation reason.  It does **not**
        directly cancel S4 jobs — that is the execution layer's
        responsibility.

        Args:
            state: Current agent state.
            reason: Human-readable reason for cancellation.
            details: Optional structured details.

        Returns:
            Updated ``AgentState`` in ``FAILED`` state.

        Raises:
            AgentInTerminalStateError: If state is already terminal.
        """
        self._require_not_terminal(state)

        errors = list(state.errors)
        errors.append({
            "type": "cancellation",
            "message": reason,
            "details": details or {},
        })

        return self._persist(state.with_(
            lifecycle_state=LifecycleState.FAILED,
            errors=errors,
            _reason=reason,
            _details=details or {},
        ))

    # ── 7. complete_agent ──────────────────────────────────────────────

    def complete_agent(
        self,
        state: AgentState,
        response: AgentResponse,
    ) -> AgentState:
        """Mark an agent as completed with a final response.

        Valid from any non-terminal state.  Transitions to COMPLETED.

        Args:
            state: Current agent state.
            response: Final ``AgentResponse`` to deliver to the user.

        Returns:
            Updated ``AgentState`` in ``COMPLETED`` state.

        Raises:
            AgentInTerminalStateError: If state is already terminal.
        """
        self._require_not_terminal(state)

        return self._persist(state.with_(
            lifecycle_state=LifecycleState.COMPLETED,
            final_response=response,
            _reason="Agent completed with final response",
            _details={
                "has_reply": response.reply is not None,
            },
        ))

    # ── 8. get_response ────────────────────────────────────────────────

    @staticmethod
    def get_response(state: AgentState) -> Optional[AgentResponse]:
        """Retrieve the final ``AgentResponse`` (if any).

        Returns ``None`` if the agent has not yet produced a final
        response (e.g. it is still RUNNING or WAITING).
        """
        return state.final_response

    # ── 9. get_lifecycle_history ───────────────────────────────────────

    @staticmethod
    def get_lifecycle_history(state: AgentState) -> List[LifecycleEvent]:
        """Return the full lifecycle event history for audit/debug."""
        return list(state.lifecycle_history)

    # ── Internal helpers ───────────────────────────────────────────────

    def _require_not_terminal(self, state: AgentState) -> None:
        """Guard: raise if the agent is in a terminal state."""
        if state.is_terminal():
            raise AgentInTerminalStateError(
                f"agent {state.agent_id!r} is in terminal state "
                f"{state.lifecycle_state.value}; no further transitions allowed"
            )

    def _persist(self, state: AgentState) -> AgentState:
        """Persist the state snapshot if auto-persist is enabled.

        Returns the state unchanged (pass-through for convenience).
        """
        if self._auto_persist:
            self._store.save(state.agent_id, state)
        return state

    @staticmethod
    def _compute_duration_ms(timestamp_iso: str) -> float:
        """Compute duration from *timestamp_iso* to now in milliseconds.

        Returns 0 if the timestamp is empty or unparseable.
        """
        if not timestamp_iso:
            return 0.0
        try:
            start = datetime.fromisoformat(timestamp_iso)
            delta = datetime.now(timezone.utc) - start.replace(
                tzinfo=timezone.utc
            )
            return delta.total_seconds() * 1000.0
        except (ValueError, TypeError):
            return 0.0

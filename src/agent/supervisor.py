"""
Phase 5.5 — Agent Runtime Supervisor
======================================

The supervisor is the **top-level agent execution orchestrator**.  It owns
the full lifecycle of an agent instance — creation, activation, cognitive
loop execution, job dispatch, suspension, cancellation, and completion.

S5.5 does **not**:
- call LLMs
- execute tools
- invoke skills
- perform cognitive reasoning
- mutate S4 state
- define new execution semantics

S5.5 coordinates S5.3 (cognitive loop) and S5.4 (job interface) via their
existing public APIs.

Public API
----------
- ``create_agent``  — instantiate runtime state for a registered agent
- ``activate_agent`` — delegate to S5.2 to build activation context
- ``run_agent_step`` — one complete think -> dispatch iteration
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
from src.agent.cognitive_loop import (
    CognitiveLoopResult,
    run_cognitive_loop,
)
from src.agent.contracts import AgentMessage, AgentResponse, ActionIntent
from src.agent.interfaces.agent_state import (
    AgentState,
    LifecycleEvent,
    LifecycleState,
)
from src.agent.interfaces.agent_state_store import AgentStateStore
from src.agent.job_interface import (
    JobDispatchResult,
    dispatch_action_intents,
)
from src.agent.registry import AgentRegistry, AgentNotFoundError
from src.capabilities.interfaces import SkillRunner
from src.platform.transport.normalization import ChannelMessage

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
        skill_runner: Optional[SkillRunner] = None,
        submit_job_callable: Optional[Callable[[ChannelMessage], str]] = None,
        default_backend: str = "simulation",
        default_max_iterations: int = 5,
        auto_persist: bool = True,
    ) -> None:
        self._registry = registry
        self._store = store
        self._skill_runner = skill_runner
        self._submit_job = submit_job_callable
        self._default_backend = default_backend
        self._default_max_iterations = default_max_iterations
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
                "backend": self._default_backend,
                "max_iterations": metadata.constraints.max_tokens
                if metadata.constraints.max_tokens > 0
                else self._default_max_iterations,
                "timeout_ms": metadata.constraints.timeout_ms,
                "total_iterations": 0,
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
        backend: Optional[str] = None,
        max_iterations: Optional[int] = None,
    ) -> AgentState:
        """Execute one complete agent iteration: think -> dispatch.

        1. Transition to RUNNING
        2. Call S5.3 ``run_cognitive_loop()`` with the activation snapshot
        3. Store ``CognitiveLoopResult`` in state
        4. Call S5.4 ``dispatch_action_intents()`` with the result
        5. Store ``JobDispatchResult`` in state
        6. Determine next lifecycle state:
           - If pending jobs were dispatched -> WAITING
           - If terminal intents produced -> check for final response
           - If errors -> SUSPENDED or FAILED depending on severity
        7. Return new state

        Args:
            state: Current agent state (must be ACTIVATED or RUNNING/WAITING
                   for continuation).
            backend: S1 backend override.
            max_iterations: Cognitive loop iterations override.

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
            # This should not happen if the lifecycle is respected, but
            # guard against it.
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
                _reason="Missing activation snapshot — cannot run cognitive loop",
            ))

        # 3. Run cognitive loop (S5.3)
        cognitive_backend = backend or self._default_backend
        loop_iterations = max_iterations or state.supervisor_metadata.get(
            "max_iterations", self._default_max_iterations
        )

        cognitive_result = run_cognitive_loop(
            context=ctx,
            max_iterations=loop_iterations,
            backend=cognitive_backend,
            skill_runner=self._skill_runner,
        )

        # 4. Dispatch action intents (S5.4)
        dispatch_result = dispatch_action_intents(
            result=cognitive_result,
            context=ctx,
            submit_job_callable=self._submit_job,
        )

        total_iterations = (
            state.supervisor_metadata.get("total_iterations", 0)
            + 1
        )

        # 5. Determine next state
        new_errors = list(state.errors)
        if cognitive_result.errors:
            for err in cognitive_result.errors:
                new_errors.append({
                    "type": "cognitive_loop_error",
                    "message": err.get("message", str(err)),
                    "details": err.get("details", {}),
                })
        if dispatch_result.errors:
            for intent_type, err_msg in dispatch_result.errors:
                new_errors.append({
                    "type": "dispatch_error",
                    "intent_type": intent_type,
                    "message": err_msg,
                })

        has_fatal_errors = any(
            e.get("type") in ("cognitive_loop_error",)
            and e.get("message", "").startswith("Safe fallback")
            for e in new_errors[len(state.errors):]
        )

        # Collect pending intents from both sources
        pending: List[ActionIntent] = list(cognitive_result.action_intents)

        # Determine if there are dispatched jobs (means we're waiting)
        has_dispatched = len(dispatch_result.dispatched_jobs) > 0

        # Determine if there are terminal intents (conversational reply)
        has_terminal = len(dispatch_result.terminal_intents) > 0

        # Build base metadata
        meta = dict(state.supervisor_metadata)
        meta["total_iterations"] = total_iterations

        if has_fatal_errors:
            # Unrecoverable — transition to FAILED
            return self._persist(state.with_(
                lifecycle_state=LifecycleState.FAILED,
                cognitive_result=cognitive_result,
                dispatch_result=dispatch_result,
                errors=new_errors,
                supervisor_metadata=meta,
                _reason="Cognitive loop encountered unrecoverable error",
                _details={"error_count": len(new_errors)},
            ))

        if has_dispatched:
            # Jobs submitted — transition to WAITING
            return self._persist(state.with_(
                lifecycle_state=LifecycleState.WAITING,
                cognitive_result=cognitive_result,
                dispatch_result=dispatch_result,
                pending_intents=pending,
                errors=new_errors,
                supervisor_metadata=meta,
                _reason=f"Dispatched {len(dispatch_result.dispatched_jobs)} jobs — awaiting results",
                _details={
                    "dispatched_count": len(dispatch_result.dispatched_jobs),
                },
            ))

        if has_terminal:
            # No jobs needed, agent produced a conversational response
            return self._persist(state.with_(
                lifecycle_state=LifecycleState.COMPLETED,
                cognitive_result=cognitive_result,
                dispatch_result=dispatch_result,
                pending_intents=None,
                final_response=AgentResponse(
                    reply=cognitive_result.thought.get("message"),
                    actions=cognitive_result.action_intents,
                    metadata={
                        "correlation_id": state.correlation_id,
                        "trace_id": state.trace_id,
                        "agent_id": state.agent_id,
                        "confidence": cognitive_result.confidence,
                        "iteration_count": cognitive_result.iteration_count,
                    },
                ),
                errors=new_errors,
                supervisor_metadata=meta,
                _reason="Agent produced final conversational response",
                _details={
                    "confidence": cognitive_result.confidence,
                    "iteration_count": cognitive_result.iteration_count,
                },
            ))

        # No dispatched jobs and no terminal intents — edge case, treat as
        # completed with no output.
        return self._persist(state.with_(
            lifecycle_state=LifecycleState.COMPLETED,
            cognitive_result=cognitive_result,
            dispatch_result=dispatch_result,
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
                "action_count": len(response.actions),
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

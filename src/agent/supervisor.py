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

import re
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
from src.agent.router import DEST_RUNTIME, DEST_S4B, DEST_WORKFLOW, Route, route_message
from src.agent.workflow import WorkflowEngine, WorkflowInstanceStore, WorkflowRegistry
from src.agent.workflow.engine import WorkflowExecutionState, WorkflowStatus
from src.agent.workflow.user_interaction import UserInteractionManager
from src.agent.strategy_router import RouterOutcome, StrategyRouter

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
        workflow_registry: Optional[WorkflowRegistry] = None,
        workflow_engine: Optional[WorkflowEngine] = None,
        workflow_instance_store: Optional[WorkflowInstanceStore] = None,
        interaction_manager: Optional[UserInteractionManager] = None,
        strategy_router: Optional[StrategyRouter] = None,
        auto_persist: bool = True,
        inline_tool_executor: Optional[Callable[[dict[str, Any]], dict[str, Any] | None]] = None,
    ) -> None:
        self._registry = registry
        self._store = store
        self._submit_job = submit_job_callable
        self._workflow_registry = workflow_registry
        self._workflow_engine = workflow_engine
        self._workflow_store = workflow_instance_store or WorkflowInstanceStore()
        self._interaction_manager = interaction_manager
        self._strategy_router = strategy_router or StrategyRouter()
        self._auto_persist = auto_persist
        self._inline_tool_executor = inline_tool_executor

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
           - ``DEST_WORKFLOW`` → mark as WAITING (workflow dispatch TBD)
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
            # LLM conversation path — route via StrategyRouter
            agent_meta = ctx.context.agent_metadata
            outcome = RouterOutcome(
                type="llm_call",
                payload={
                    "prompt": {
                        "message": input_text,
                        "agent_id": agent_meta.identity.agent_id,
                        "agent_metadata": {
                            "name": agent_meta.identity.name,
                            "description": agent_meta.identity.description,
                        },
                    },
                    "backend": "conversational",
                    "memory": {
                        "conversation_history":
                            ctx.context.conversation_history,
                    },
                    "plan_context": {},
                    "tool_context": [],
                },
            )
            result = self._strategy_router.route(outcome)

            reply: str = "I'm not sure how to respond."
            metadata: Dict[str, Any] = {
                "correlation_id": state.correlation_id,
                "trace_id": state.trace_id,
                "agent_id": state.agent_id,
                "confidence": route.confidence,
                "route_destination": route.destination,
            }
            _reason = "Agent produced conversational response via Runtime route"
            if result.get("error") is None:
                reply = result["output"].get("message", reply)
                if result.get("runtime_fallback"):
                    metadata["runtime_fallback"] = True
                    metadata["runtime_error"] = result["runtime_error"]
                    _reason = "Agent produced conversational response via mock fallback"
            else:
                reply = f"[Runtime unavailable: {result['error']}]"
                metadata["runtime_error"] = result["error"]

            return self._persist(state.with_(
                lifecycle_state=LifecycleState.COMPLETED,
                route_result=route,
                final_response=AgentResponse(reply=reply, metadata=metadata),
                supervisor_metadata=meta,
                _reason=_reason,
                _details={
                    "confidence": route.confidence,
                    "route_destination": route.destination,
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

        if route.destination == DEST_WORKFLOW:
            if self._workflow_registry is None:
                new_errors.append({
                    "type": "workflow_not_configured",
                    "message": "Workflow route matched but no workflow registry configured",
                })
                return self._persist(state.with_(
                    lifecycle_state=LifecycleState.COMPLETED,
                    route_result=route,
                    errors=new_errors,
                    supervisor_metadata=meta,
                    _reason="Workflow registry not configured",
                    _details={"route_destination": route.destination},
                ))

            workflow_id = route.payload.get("workflow_id") or state.agent_id
            engine = self._workflow_engine or WorkflowEngine(self._workflow_registry)

            # ── Resume path (workflow state exists in metadata) ────────
            wf_dict = meta.get("workflow_state")
            if wf_dict is not None:
                wf_state = _restore_wf_state(wf_dict)
                waiting_for = meta.get("workflow_waiting_for", "")
                if waiting_for == "user_input":
                    request_id = meta.get("workflow_interaction_request_id", "")
                    if request_id and self._interaction_manager is not None:
                        valid, err, result = self._interaction_manager.submit_response(
                            request_id, {"text": input_text}, wf_state,
                        )
                        if not valid:
                            new_errors.append({
                                "type": "interaction_error",
                                "message": err or "Invalid interaction response",
                            })
                            # Fall back to raw resume so the workflow doesn't stall
                            wf_state, _outcome = engine.resume_with_input(
                                wf_state, input_text,
                            )
                        else:
                            wf_state, _outcome = result
                    else:
                        wf_state, _outcome = engine.resume_with_input(
                            wf_state, input_text,
                        )
                elif waiting_for == "tool_result":
                    result = meta.get("workflow_last_result", {})
                    last_step = meta.get("workflow_last_step_id", "")
                    wf_state, _outcome = engine.resume_with_result(
                        wf_state, last_step, result,
                    )
                # else: just run step() on the restored state
                return self._run_workflow_loop(
                    state, engine, wf_state, route, meta, new_errors,
                )

            # ── Start path ───────────────────────────────────────────
            try:
                wf_state = engine.start_workflow(
                    workflow_id, context={
                        "input": input_text,
                        "message": input_text,
                    },
                )
            except ValueError as exc:
                new_errors.append({
                    "type": "workflow_not_found",
                    "message": str(exc),
                })
                return self._persist(state.with_(
                    lifecycle_state=LifecycleState.FAILED,
                    route_result=route,
                    errors=new_errors,
                    supervisor_metadata=meta,
                    _reason=str(exc),
                    _details={"route_destination": route.destination},
                ))

            return self._run_workflow_loop(
                state, engine, wf_state, route, meta, new_errors,
            )

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

    # ── ─ Workflow execution loop ───────────────────────────────────────

    _WF_MAX_ITERATIONS = 50
    """Safety limit on sequential step iterations within one call."""

    def _run_workflow_loop(
        self,
        state: AgentState,
        engine: WorkflowEngine,
        wf_state: WorkflowExecutionState,
        route: Route,
        meta: Dict[str, Any],
        new_errors: List[Dict[str, Any]],
    ) -> AgentState:
        """Deterministic step-processing loop.

        Processes steps until a blocking outcome (tool_execute,
        waiting_for_input) or a terminal outcome (completed, failed)
        is reached.
        """
        iteration = 0

        wf_store = self._workflow_store

        while iteration < self._WF_MAX_ITERATIONS:
            iteration += 1
            wf_state, outcome = engine.step(wf_state)
            wf_store.save(wf_state)

            # ── Deterministic transitions ──────────────────────────
            if outcome.type == "continue":
                continue

            # ── Terminal ───────────────────────────────────────────
            if outcome.type == "completed":
                meta.pop("workflow_state", None)
                meta.pop("workflow_waiting_for", None)
                final_msg = (
                    wf_state.context.get("_workflow_result")
                    or wf_state.context.get("result")
                    or "Workflow completed successfully."
                )
                return self._persist(state.with_(
                    lifecycle_state=LifecycleState.COMPLETED,
                    route_result=route,
                    final_response=AgentResponse(
                        reply=str(final_msg),
                        metadata={
                            "correlation_id": state.correlation_id,
                            "trace_id": state.trace_id,
                            "agent_id": state.agent_id,
                            "workflow_id": wf_state.workflow_id,
                            "route_destination": route.destination,
                        },
                    ),
                    supervisor_metadata=meta,
                    _reason="Workflow completed",
                    _details={
                        "workflow_id": wf_state.workflow_id,
                        "execution_id": wf_state.execution_id,
                    },
                ))

            if outcome.type == "failed":
                meta.pop("workflow_state", None)
                meta.pop("workflow_waiting_for", None)
                return self._persist(state.with_(
                    lifecycle_state=LifecycleState.FAILED,
                    route_result=route,
                    errors=(list(state.errors) + new_errors + [{
                        "type": "workflow_step_failed",
                        "step_id": outcome.step_id,
                        "message": outcome.error or "Unknown workflow error",
                    }]),
                    supervisor_metadata=meta,
                    _reason=f"Workflow failed: {outcome.error}",
                    _details={
                        "workflow_id": wf_state.workflow_id,
                        "step_id": outcome.step_id,
                    },
                ))

            # ── LLM call → route via StrategyRouter → resume / fail ──
            if outcome.type == "llm_call":
                rendered_config = _render_context_templates(
                    outcome.config,
                    wf_state.context,
                    wf_state.step_results,
                )
                router_outcome = RouterOutcome(
                    type="llm_call",
                    payload={
                        "prompt": rendered_config,
                        "backend": "conversational",
                        "memory": {},
                        "plan_context": {},
                        "tool_context": [],
                    },
                    step_id=outcome.step_id,
                )
                result = self._strategy_router.route(router_outcome)
                if result.get("error") is None:
                    wf_state, _ = engine.resume_with_result(
                        wf_state, outcome.step_id, result["output"],
                    )
                else:
                    wf_state, _ = engine.fail_step(
                        wf_state, outcome.step_id, result["error"],
                    )
                wf_store.save(wf_state)
                continue

            # ── Tool execute → dispatch to S4B → WAITING ──────────
            if outcome.type == "tool_execute":
                # Try inline tool execution first
                if self._inline_tool_executor is not None:
                    try:
                        inline_result = self._inline_tool_executor(outcome.config)
                    except Exception:
                        inline_result = None
                    if inline_result is not None:
                        wf_state, _ = engine.resume_with_result(
                            wf_state, outcome.step_id, inline_result,
                        )
                        wf_store.save(wf_state)
                        continue

                tool_route = Route(
                    destination=DEST_S4B,
                    payload=outcome.config,
                    agent_id=state.agent_id,
                )
                dispatch_result = dispatch_route(
                    route=tool_route,
                    submit_job_callable=self._submit_job,
                )
                if dispatch_result.errors:
                    for _jid, err_msg in dispatch_result.errors:
                        new_errors.append({
                            "type": "workflow_dispatch_error",
                            "step_id": outcome.step_id,
                            "message": err_msg,
                        })

                if dispatch_result.dispatched_jobs:
                    meta["workflow_state"] = _freeze_wf_state(wf_state)
                    meta["workflow_waiting_for"] = "tool_result"
                    meta["workflow_last_step_id"] = outcome.step_id
                    meta["workflow_last_result"] = {}
                    return self._persist(state.with_(
                        lifecycle_state=LifecycleState.WAITING,
                        route_result=route,
                        dispatch_result=dispatch_result,
                        errors=(list(state.errors) + new_errors),
                        supervisor_metadata=meta,
                        _reason=(
                            f"Workflow dispatched "
                            f"{len(dispatch_result.dispatched_jobs)} jobs"
                        ),
                        _details={
                            "workflow_id": wf_state.workflow_id,
                            "step_id": outcome.step_id,
                        },
                    ))

                # No jobs dispatched → treat as step failure
                wf_state, _ = engine.fail_step(
                    wf_state, outcome.step_id,
                    "tool_execute dispatched zero jobs",
                )
                wf_store.save(wf_state)
                continue

            # ── User input → WAITING ───────────────────────────────
            if outcome.type == "waiting_for_input":
                meta["workflow_state"] = _freeze_wf_state(wf_state)
                meta["workflow_waiting_for"] = "user_input"

                # Register an interaction request with the manager
                if self._interaction_manager is not None:
                    step_config = outcome.config or {}
                    prompt = step_config.get("prompt", "Please provide input:")
                    schema = step_config.get("input_schema", {})
                    req = self._interaction_manager.request_input(
                        instance_id=wf_state.workflow_id,
                        step_id=outcome.step_id,
                        prompt=prompt,
                        schema=schema,
                        timeout_seconds=step_config.get("timeout_seconds"),
                    )
                    meta["workflow_interaction_request_id"] = req.request_id
                    meta["workflow_interaction_prompt"] = prompt

                return self._persist(state.with_(
                    lifecycle_state=LifecycleState.WAITING,
                    route_result=route,
                    errors=(list(state.errors) + new_errors),
                    supervisor_metadata=meta,
                    _reason="Workflow waiting for user input",
                    _details={
                        "workflow_id": wf_state.workflow_id,
                        "step_id": outcome.step_id,
                    },
                ))

            # ── Planner call → route via StrategyRouter → resume ──
            if outcome.type == "planner_call":
                rendered_config = _render_context_templates(
                    outcome.config,
                    wf_state.context,
                    wf_state.step_results,
                )
                router_outcome = RouterOutcome(
                    type="planner_call",
                    payload={
                        "goal": rendered_config.get("goal", ""),
                        "context": wf_state.context,
                    },
                    step_id=outcome.step_id,
                )
                result = self._strategy_router.route(router_outcome)
                if result.get("error") is None:
                    wf_state, _ = engine.resume_with_result(
                        wf_state, outcome.step_id, result["output"],
                    )
                else:
                    wf_state, _ = engine.fail_step(
                        wf_state, outcome.step_id, result["error"],
                    )
                wf_store.save(wf_state)
                continue

            # ── Sub-workflow → start and loop ──────────────────────
            if outcome.type == "sub_workflow":
                sub_id = outcome.workflow_id or ""
                try:
                    wf_state = engine.start_workflow(
                        sub_id, context=dict(wf_state.context),
                    )
                except ValueError as exc:
                    wf_state, _ = engine.fail_step(
                        wf_state, outcome.step_id,
                        f"sub-workflow {sub_id!r}: {exc}",
                    )
                wf_store.save(wf_state)
                continue

            # ── Unreachable guard ───────────────────────────────────
            meta.pop("workflow_state", None)
            meta.pop("workflow_waiting_for", None)
            return self._persist(state.with_(
                lifecycle_state=LifecycleState.FAILED,
                route_result=route,
                errors=(list(state.errors) + new_errors + [{
                    "type": "workflow_unknown_outcome",
                    "message": f"Unknown outcome type {outcome.type!r}",
                }]),
                supervisor_metadata=meta,
                _reason=f"Unknown outcome type {outcome.type!r}",
            ))

        # ── Iteration limit ────────────────────────────────────────
        meta.pop("workflow_state", None)
        meta.pop("workflow_waiting_for", None)
        return self._persist(state.with_(
            lifecycle_state=LifecycleState.FAILED,
            route_result=route,
            errors=(list(state.errors) + new_errors + [{
                "type": "workflow_iteration_limit",
                "message": (
                    f"Workflow exceeded "
                    f"{self._WF_MAX_ITERATIONS} iterations"
                ),
            }]),
            supervisor_metadata=meta,
            _reason=f"Exceeded {self._WF_MAX_ITERATIONS} step iterations",
        ))

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

    # ── State access ─────────────────────────────────────────────────

    def get_agent_state(self, agent_id: str) -> AgentState:
        """Load agent state from the store by agent ID.

        Args:
            agent_id: The agent's unique identifier.

        Returns:
            The agent's current ``AgentState``.

        Raises:
            SupervisorError: If no agent exists with the given ID.
        """
        state = self._store.load(agent_id)
        if state is None:
            raise SupervisorError(
                f"No agent found with id '{agent_id}'",
            )
        return state

    # ── S4B job-result injection (for callbacks / test sims) ─────────

    def set_tool_result(
        self,
        agent_id: str,
        result: Dict[str, Any],
    ) -> AgentState:
        """Inject a tool result into a WAITING agent's metadata.

        Simulates the S4B job-completion callback.  After calling this
        method, invoke ``run_agent_step`` with a message that routes
        ``DEST_WORKFLOW`` to resume the workflow with the injected result.

        Args:
            agent_id: The agent whose tool result to set.
            result:   The tool result payload (becomes
                      ``workflow_last_result`` in metadata).

        Returns:
            The updated ``AgentState`` (saved to store).

        Raises:
            SupervisorError: If the agent does not exist.
        """
        state = self.get_agent_state(agent_id)
        meta = dict(state.supervisor_metadata)
        meta["workflow_last_result"] = result
        return self._persist(state.with_(supervisor_metadata=meta))

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


# ── Workflow state serialisation helpers ─────────────────────────────


def _freeze_wf_state(wf_state: WorkflowExecutionState) -> Dict[str, Any]:
    """Serialise ``WorkflowExecutionState`` to a JSON-safe dict.

    The result is stored in ``supervisor_metadata["workflow_state"]``
    to survive WAITING → resume cycles.
    """
    return {
        "execution_id": wf_state.execution_id,
        "workflow_id": wf_state.workflow_id,
        "current_step_id": wf_state.current_step_id,
        "context": dict(wf_state.context),
        "step_results": dict(wf_state.step_results),
        "status": wf_state.status.value,
        "error": wf_state.error,
    }


def _render_context_templates(
    config: Dict[str, Any],
    context: Dict[str, Any],
    step_results: Dict[str, Any],
) -> Dict[str, Any]:
    """Replace ``{context.X}`` and ``{result.X}`` placeholders in config values.

    Scans every string value in the config dict and substitutes:
      - ``{context.key}`` -> ``context.get("key", "")``
      - ``{result.step_id}`` -> ``step_results.get("step_id", "")``
    """
    rendered: Dict[str, Any] = {}
    for key, raw_value in config.items():
        if not isinstance(raw_value, str):
            rendered[key] = raw_value
            continue

        def _replace(m: re.Match) -> str:
            namespace = m.group(1)
            name = m.group(2)
            if namespace == "context":
                return str(context.get(name, ""))
            if namespace == "result":
                return str(step_results.get(name, ""))
            return m.group(0)

        rendered[key] = re.sub(
            r"\{(context|result)\.([a-zA-Z_0-9]+)\}",
            _replace,
            raw_value,
        )
    return rendered


def _restore_wf_state(d: Dict[str, Any]) -> WorkflowExecutionState:
    """Deserialise a dict back into a ``WorkflowExecutionState``."""
    return WorkflowExecutionState(
        execution_id=d["execution_id"],
        workflow_id=d["workflow_id"],
        current_step_id=d.get("current_step_id"),
        context={k: v for k, v in d.get("context", {}).items()},
        step_results={k: v for k, v in d.get("step_results", {}).items()},
        status=WorkflowStatus(d["status"]),
        error=d.get("error"),
    )

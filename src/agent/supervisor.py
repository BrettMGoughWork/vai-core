"""
Phase 5.5 — Agent Runtime Supervisor
======================================

The supervisor is the **top-level agent execution orchestrator**.  It owns
the full lifecycle of an agent instance — creation, activation, message
routing, job dispatch, suspension, cancellation, and completion.

S5.5 does **not**:
- call LLMs
- execute tools
- execute tools
- perform cognitive reasoning
- mutate S4 state
- define new execution semantics

S5.5 coordinates the Agent Router (S5.2) and the job interface (S5.4) to
route incoming messages to the appropriate destination: Runtime (LLM
conversation), S6 (workflow orchestration), or S4B (capability execution).

Public API
----------
- ``create_agent``    — instantiate runtime state for a registered agent
- ``activate_agent``  — delegate to S5.2 to build activation context
- ``run_agent_step``  — route message -> dispatch to Runtime/S6/S4B
- ``suspend_agent``   — pause agent execution (timeout / external signal)
- ``resume_agent``    — restore a suspended agent to RUNNING
- ``defer_to_agent``  — hand off work to a delegate agent (suspend→delegate→resume)
- ``cancel_agent``    — terminate agent execution (manual or system)
- ``complete_agent``  — mark agent as completed with a final response
- ``get_response``    — retrieve the final AgentResponse (if any)
- ``get_lifecycle_history`` — full audit trail of lifecycle events
"""

from __future__ import annotations

import json
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
from src.agent.guards import apply_hallucination_guard
from src.agent.hitl_manager import HitlManager
from src.agent.planner.todo_orchestrator import TodoOrchestrator
from src.agent.tool_orchestrator import ToolOrchestrator
from src.agent.workflow_invoker import WorkflowInvoker
from src.agent.workflow_invoker import (
    WorkflowInvoker,
    _freeze_wf_state,
    _render_context_templates,
    _restore_wf_state,
)
from src.agent.interfaces.agent_state import (
    AgentState,
    LifecycleEvent,
    LifecycleState,
)
from src.agent.interfaces.agent_state_store import AgentStateStore
from src.agent.job_interface import JobDispatchResult, dispatch_route
from src.agent.registry import AgentRegistry, AgentNotFoundError
from src.agent.registry import AgentRegistry, AgentNotFoundError  # noqa: F811
from src.agent.router import DEST_RUNTIME, DEST_S4B, DEST_WORKFLOW, Route, route_message
from src.agent.selection import AgentSelectionStrategy
from src.agent.workflow import WorkflowEngine, WorkflowInstanceStore, WorkflowRegistry
from src.agent.workflow.engine import WorkflowExecutionState, WorkflowStatus
from src.agent.workflow.user_interaction import UserInteractionManager
from src.capabilities.patterns.pattern_registry import PatternRegistry
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
        workflow_tool_adapter: Optional[Any] = None,
        primitive_tool_adapter: Optional[Any] = None,
        pattern_registry: Optional[PatternRegistry] = None,
        todo_orchestrator: Optional[TodoOrchestrator] = None,
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
        self._agent_selector = (
            AgentSelectionStrategy(registry) if registry is not None else None
        )
        self._workflow_tool_adapter = workflow_tool_adapter
        self._primitive_tool_adapter = primitive_tool_adapter
        self._pattern_registry = pattern_registry
        self._todo_orchestrator = todo_orchestrator
        self._hitl = HitlManager(
            inline_tool_executor=inline_tool_executor,
            strategy_router=strategy_router,
        )
        self._tool_orchestrator = ToolOrchestrator(
            workflow_engine=workflow_engine,
            workflow_store=self._workflow_store,
            inline_tool_executor=inline_tool_executor,
            strategy_router=strategy_router,
        )
        self._workflow_invoker = WorkflowInvoker(
            workflow_engine=workflow_engine,
            workflow_store=self._workflow_store,
            strategy_router=strategy_router,
            inline_tool_executor=inline_tool_executor,
            submit_job=submit_job_callable,
            interaction_manager=interaction_manager,
            agent_selector=self._agent_selector,
            registry=registry,
            workflow_tool_adapter=workflow_tool_adapter,
            primitive_tool_adapter=primitive_tool_adapter,
        )
    
    @staticmethod
    def _filter_tool_context(
        tool_context: list[dict],
        skills: list[str],
    ) -> list[dict]:
        """Filter *tool_context* to only include tools matching *skills*.

        If *skills* is empty or contains ``"*"``, no filtering is applied
        (the agent has access to all registered tools).  Otherwise, each
        tool's function name must contain a skill pattern as a substring
        or match via fnmatch glob (e.g. ``gmail_*``).

        Tool names and patterns are both normalised (dots → underscores)
        before matching so that patterns like ``gmail_search`` match tool
        names like ``primitive.custom.gmail.search``.  This is consistent
        with the name sanitisation applied before sending tools to LLMs
        (most providers reject dots in tool names).
        """
        if not skills or "*" in skills:
            return tool_context

        import fnmatch
        import re

        _NON_SAFE = re.compile(r"[^a-zA-Z0-9_-]")

        filtered: list[dict] = []
        for tool in tool_context:
            func_name = (
                (tool.get("function", {})
                 if isinstance(tool.get("function"), dict)
                 else {}).get("name", "")
                or tool.get("name", "")
            )
            normalized_name = _NON_SAFE.sub("_", func_name)
            for pattern in skills:
                normalized_pattern = _NON_SAFE.sub("_", pattern)
                if normalized_pattern in normalized_name or fnmatch.fnmatch(
                    normalized_name, f"*{normalized_pattern}*"
                ):
                    filtered.append(tool)
                    break
        return filtered

    def _resolve_pattern_primitives(self, agent_meta) -> list[str]:
        """Expand the agent's patterns into their required primitive tool names.

        Patterns act as capability gateways — an agent that lists pattern-X
        gets access to pattern-X's primitives without needing to list them
        explicitly in ``tools``.  Returns the union of the agent's explicit
        ``tools`` and all primitives declared by the agent's patterns.
        """
        if not self._pattern_registry:
            return list(agent_meta.tools)
        all_tools = set(agent_meta.tools)
        for pid in agent_meta.patterns:
            pattern = self._pattern_registry.get(pid)
            if pattern:
                all_tools.update(pattern.primitives)
        return sorted(all_tools)

    def _get_pattern_instructions(self, agent_meta) -> list[dict]:
        """Return pattern instructions for patterns listed by the agent.

        Each entry includes pattern_id, name, and instructions — intended
        for injection into the LLM system prompt as contextual guidance.
        """
        if not self._pattern_registry:
            return []
        result: list[dict] = []
        for pid in agent_meta.patterns:
            pattern = self._pattern_registry.get(pid)
            if pattern:
                result.append({
                    "pattern_id": pattern.pattern_id,
                    "name": pattern.name,
                    "instructions": pattern.instructions,
                })
        return result

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
            # ── Resume path: user responding to a HITL confirmation prompt ─
            pending = meta.pop("pending_tool_calls", None)
            if pending is not None:
                meta.pop("waiting_for", None)
                agent_meta = ctx.context.agent_metadata
                # Build tool_context for the follow-up LLM
                tool_context: list[dict] = []
                if self._workflow_tool_adapter is not None:
                    tool_context = self._workflow_tool_adapter.list_tools()
                if self._primitive_tool_adapter is not None:
                    primitive_tools = self._primitive_tool_adapter.list_tools()
                    tool_context.extend(primitive_tools)
                tool_context = self._filter_tool_context(
                    tool_context, self._resolve_pattern_primitives(agent_meta),
                )
                return self._hitl.run_confirmed_skills(
                    state, pending, input_text, route, meta, self._persist,
                    agent_meta=agent_meta,
                    tool_context=tool_context,
                    conversation_history=ctx.context.conversation_history,
                    user_request=input_text,
                    pattern_instructions=self._get_pattern_instructions(agent_meta),
                )

            # LLM conversation path — route via StrategyRouter
            agent_meta = ctx.context.agent_metadata

            # Build tool_context from workflow + primitive tool adapters
            tool_context: list[dict] = []
            if self._workflow_tool_adapter is not None:
                tool_context = self._workflow_tool_adapter.list_tools()
            if self._primitive_tool_adapter is not None:
                primitive_tools = self._primitive_tool_adapter.list_tools()
                tool_context.extend(primitive_tools)

            # Filter tool_context to only include tools the agent is allowed to use.
            # When agent_meta.tools is populated, only tools whose function name
            # matches an entry (substring or fnmatch glob) are included.
            resolved_skills = self._resolve_pattern_primitives(agent_meta)
            tool_context = self._filter_tool_context(
                tool_context, resolved_skills,
            )

            # D1.8: inject defer_to synthetic tool when the agent can hand off
            if agent_meta.defer_to:
                tool_context.append(
                    self._build_defer_to_tool(agent_meta.defer_to)
                )

            outcome = RouterOutcome(
                type="llm_call",
                payload={
                    "prompt": {
                        "message": input_text,
                        "agent_id": agent_meta.identity.agent_id,
                        "agent_metadata": {
                            "name": agent_meta.identity.name,
                            "description": agent_meta.identity.description,
                            "persona": agent_meta.persona,
                            "tools": list(agent_meta.tools),
                            "workflows": list(agent_meta.workflows),
                                "patterns": self._get_pattern_instructions(agent_meta),
                        },
                    },
                    "backend": "conversational",
                    "memory": {
                        "conversation_history":
                            ctx.context.conversation_history,
                    },
                    "plan_context": {},
                    "tool_context": tool_context,
                },
            )
            result = self._strategy_router.route(outcome)

            reply: str = ""
            metadata: Dict[str, Any] = {
                "correlation_id": state.correlation_id,
                "trace_id": state.trace_id,
                "agent_id": state.agent_id,
                "confidence": route.confidence,
                "route_destination": route.destination,
            }
            _reason = "Agent produced conversational response via Runtime route"
            if result.get("error") is None:
                reply = result["output"].get("message") or reply
                # When the LLM returns tool_calls without a text message,
                # generate a meaningful placeholder instead of leaving it empty.
                if not reply and not result.get("tool_calls"):
                    reply = (
                        "I received your request but I'm not sure how to"
                        " help with that. Could you rephrase or provide"
                        " more details?"
                    )
                if result.get("runtime_fallback"):
                    metadata["runtime_fallback"] = True
                    metadata["runtime_error"] = result["runtime_error"]
                    _reason = "Agent produced conversational response via mock fallback"

                # Sprint 8.5: Hallucination guard — detect claimed side-effects without directives
                # When native tool_calls are present, the LLM chose a tool via
                # function calling — the guard is not needed.
                # Also skip when the user explicitly affirmed (e.g. "yes" to "shall I reply?")
                # to avoid false-positives on user-requested actions.
                if not result.get("tool_calls") and not self._hitl.is_affirmative(
                    input_text.strip()
                ):
                    reply = apply_hallucination_guard(reply)

                # Sprint 9a: process /invoke-workflow directives
                reply = self._workflow_invoker.handle_invoke_workflow(reply)

                # Sprint 8.5: HITL gate for native primitive.* tool_calls
                tool_calls = result.get("tool_calls", [])
                side_effect_calls = self._hitl.has_side_effect_tool_calls(tool_calls)
                if side_effect_calls:
                    if self._hitl.is_affirmative(input_text.strip()):
                        # User already affirmed — execute below in the tool_calls loop
                        pass
                    else:
                        actions = sorted(set(
                            self._hitl.describe_side_effect(c)
                            for c in side_effect_calls
                        ))
                        meta["pending_tool_calls"] = {
                            "original_reply": reply,
                            "tool_calls": tool_calls,
                            "side_effect_indices": [
                                tool_calls.index(c) for c in side_effect_calls
                            ],
                        }
                        meta["waiting_for"] = "tool_confirmation"
                        confirmation_msg = self._hitl.build_confirmation_prompt(side_effect_calls)
                        meta["tool_confirmation_prompt"] = confirmation_msg
                        reply = reply + confirmation_msg
                        return self._persist(state.with_(
                            lifecycle_state=LifecycleState.WAITING,
                            route_result=route,
                            final_response=AgentResponse(
                                reply=reply, metadata=metadata,
                            ),
                            supervisor_metadata=meta,
                            _reason=(
                                "Awaiting user confirmation for"
                                " side-effect primitive tool_calls"
                            ),
                        ))

                # D1.8: intercept defer_to tool calls — handle them in the
                # Supervisor BEFORE ToolOrchestrator processes other tools.
                # defer_to is a supervisor-level lifecycle action
                # (suspend→delegate→resume), not a primitive.
                tool_calls = result.get("tool_calls", [])
                if tool_calls:
                    _defer_calls = [
                        tc for tc in tool_calls
                        if isinstance(tc, dict) and tc.get("name", "") == "defer_to"
                        or hasattr(tc, "name") and getattr(tc, "name", "") == "defer_to"
                    ]
                    if _defer_calls:
                        for _tc in _defer_calls:
                            _args = _tc.get("arguments", _tc.get("args", {}))
                            if isinstance(_args, str):
                                _args = json.loads(_args)
                            _target = _args.get("target", "")
                            _prompt = _args.get("prompt", "")
                            if _target and _prompt:
                                state = self.defer_to_agent(state, _target, _prompt)
                                _dr = state.supervisor_metadata.get(
                                    "deferral_result", {}
                                )
                                reply += (
                                    f"\n\n[Deferred to {_target!r}: "
                                    f"{_dr.get('response', '')[:500]}]"
                                )
                        # Remove defer_to calls so ToolOrchestrator doesn't see them
                        tool_calls = [
                            tc for tc in tool_calls
                            if (
                                isinstance(tc, dict)
                                and tc.get("name", "") != "defer_to"
                            )
                            or (
                                hasattr(tc, "name")
                                and getattr(tc, "name", "") != "defer_to"
                            )
                        ]

                # Sprint 9a/18.3: handle native tool_calls via ToolOrchestrator
                reply = self._tool_orchestrator.execute_tool_plan(
                    tool_calls=tool_calls,
                    reply=reply,
                    agent_meta=agent_meta,
                    tool_context=tool_context,
                    conversation_history=ctx.context.conversation_history,
                    result=result,
                    user_request=input_text,
                    pattern_instructions=self._get_pattern_instructions(agent_meta),
                )

                # Sprint 12b: if primitive.stdlib.todo.create_* was called,
                # auto-invoke TodoOrchestrator as a first-class capability
                # to process created goals through the two-level inner loop.
                if self._todo_orchestrator is not None:
                    _todo_create_calls = [
                        tc for tc in tool_calls
                        if isinstance(tc, dict) and (
                            tc.get("name", "").startswith("primitive.stdlib.todo.create_")
                            or tc.get("function", {}).get("name", "").startswith("primitive.stdlib.todo.create_")
                        )
                    ]
                    if _todo_create_calls:
                        _first = _todo_create_calls[0]
                        _args = _first.get("arguments") or _first.get("function", {}).get("arguments", {})
                        if isinstance(_args, str):
                            try:
                                _args = json.loads(_args)
                            except json.JSONDecodeError:
                                _args = {}
                        db_path = _args.get("db_path", "todo_plan.db")
                        try:
                            orch_result = self._todo_orchestrator.run(db_path)
                            reply += f"\n\n[Plan executed: {orch_result.get('output', 'Done.')}]"
                        except Exception as exc:
                            reply += f"\n\n[Plan execution failed: {exc}]"
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
            engine = self._workflow_engine or WorkflowEngine(
                self._workflow_registry, pattern_registry=self._pattern_registry,
            )

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
                            if err and "expired" in err:
                                # Timeout — transition engine to failed/timeout state
                                step_id = meta.get("workflow_waiting_step_id", "")
                                wf_state, _outcome = engine.handle_timeout(
                                    wf_state, step_id,
                                )
                            else:
                                # Validation error — stay WAITING, preserve
                                # wf_state (still WAITING_FOR_INPUT) so the
                                # user can retry.  The interaction request
                                # remains in _pending (submit_response does
                                # NOT delete it on validation failure).
                                meta["workflow_state"] = _freeze_wf_state(wf_state)
                                return self._persist(state.with_(
                                    lifecycle_state=LifecycleState.WAITING,
                                    route_result=route,
                                    errors=(list(state.errors) + new_errors),
                                    supervisor_metadata=meta,
                                    _reason=(
                                        "Workflow waiting for user input"
                                        " (validation error)"
                                    ),
                                    _details={
                                        "workflow_id": wf_state.workflow_id,
                                        "step_id": meta.get(
                                            "workflow_waiting_step_id", "",
                                        ),
                                    },
                                ))
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
                return self._workflow_invoker.run_workflow_loop(
                    state, engine, wf_state, route, meta, new_errors, persist=self._persist,
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

            return self._workflow_invoker.run_workflow_loop(
                state, engine, wf_state, route, meta, new_errors, persist=self._persist,
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

    # ── 5b. defer_to_agent ──────────────────────────────────────────────

    @staticmethod
    def _build_defer_to_tool(defer_to_targets: List[str]) -> dict:
        """Build a synthetic ``defer_to`` tool definition for the LLM tool context.

        Only injected when the agent has a non-empty ``defer_to`` list.
        The *target* parameter is constrained to an enum of allowed peer agents.
        """
        return {
            "type": "function",
            "function": {
                "name": "defer_to",
                "description": (
                    "Hand off the current task to a specialist peer agent. "
                    "Use this when another agent is better suited to handle "
                    "the request. The peer agent will process the prompt "
                    "independently and return its result."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string",
                            "description": "The agent ID of the peer to delegate to.",
                            "enum": sorted(defer_to_targets),
                        },
                        "prompt": {
                            "type": "string",
                            "description": (
                                "A self-contained instruction for the peer agent "
                                "describing what to do. Include all necessary "
                                "context — the peer does not see the current "
                                "conversation history."
                            ),
                        },
                    },
                    "required": ["target", "prompt"],
                },
            },
        }

    def defer_to_agent(
        self,
        state: AgentState,
        target_agent_id: str,
        prompt: str,
        *,
        max_depth: int = 3,
    ) -> AgentState:
        """Hand off work from the calling agent to a delegate agent.

        Full lifecycle: **suspend** the delegator → **create + activate +
        run** the delegate to completion → inject delegate response →
        **resume** the delegator.

        The delegator must be in RUNNING or WAITING state (i.e. active).
        After this call the delegator is in RUNNING state with the
        delegate's response injected into ``supervisor_metadata`` as
        ``deferral_result`` for consumption by the next
        ``run_agent_step()``.

        Parameters
        ----------
        state:
            Current state of the delegating agent (must be active).
        target_agent_id:
            The agent to hand work off to.  Must be in the delegator's
            ``defer_to`` list and the deferral graph must be acyclic
            (enforced at registration time).
        prompt:
            Natural-language instructions describing what the delegate
            should do.
        max_depth:
            Maximum deferral chain depth (default 3).  Each deferral
            increments the chain depth counter stored in
            ``supervisor_metadata["current_deferral_depth"]``.

        Returns
        -------
        AgentState:
            Updated delegator state in RUNNING with the delegate's
            response available in ``supervisor_metadata["deferral_result"]``.

        Raises
        ------
        AgentNotActiveError:
            If the delegator is not in an active (RUNNING or WAITING) state.
        DelegateNotAllowedError:
            If *target_agent_id* is not in the delegator's ``defer_to`` list.
        DelegateSelfReferentialError:
            If the delegator attempts to defer to itself.
        DeferralDepthError:
            If the deferral chain would exceed *max_depth*.
        SupervisorError:
            If the delegate agent cannot be created, activated, or run.
        """

        from src.agent.deferral import (
            ContextBridge,
            DepthGuard,
            DelegateNotAllowedError,
            DelegateSelfReferentialError,
            DeferralDepthError,
            DeferralResolver,
        )

        self._require_not_terminal(state)

        if not state.is_active():
            raise AgentNotActiveError(
                f"cannot defer from agent {state.agent_id!r} in "
                f"state {state.lifecycle_state.value}; "
                f"expected RUNNING or WAITING"
            )

        # ── 1. Resolve the delegate ─────────────────────────────────
        resolver = DeferralResolver(self._registry)
        delegate_meta = resolver.resolve(state.agent_id, target_agent_id)

        # ── 2. Check depth guard ────────────────────────────────────
        depth_guard = DepthGuard(max_depth=max_depth)
        current_depth = state.supervisor_metadata.get(
            "current_deferral_depth", 0
        )
        next_depth = depth_guard.get_next_depth(current_depth)

        # ── 3. Suspend the delegator ────────────────────────────────
        state = self.suspend_agent(
            state,
            reason=f"Deferring to {delegate_meta.identity.name} "
                   f"({target_agent_id})",
            details={
                "deferral_target": target_agent_id,
                "deferral_prompt": prompt[:200],
            },
        )

        # ── 4. Build delegate prompt ────────────────────────────────
        activation = state.activation_snapshot
        conversation_history: list = (
            activation.context.conversation_history
            if activation and activation.context
            else []
        )
        user_message = state.activation_snapshot.envelope.message.message if (
            activation and activation.envelope and activation.envelope.message
        ) else prompt

        delegate_prompt = ContextBridge.build_delegate_prompt(
            delegator_id=state.agent_id,
            delegator_name=(
                self._registry.get_agent(state.agent_id).identity.name
            ),
            user_message=user_message,
            deferral_prompt=prompt,
            conversation_history=conversation_history,
        )

        # ── 5. Create delegate ──────────────────────────────────────
        delegate_state = self.create_agent(target_agent_id)
        delegate_msg = AgentMessage(
            message=delegate_prompt,
            context={"origin": "deferral", "delegator_id": state.agent_id},
        )

        delegate_state = self.activate_agent(
            delegate_state,
            delegate_msg,
            channel="system",
            conversation_history=[],
        )

        # Wire depth into the delegate's metadata so it can defer further
        meta = dict(delegate_state.supervisor_metadata)
        meta["current_deferral_depth"] = next_depth
        delegate_state = self._persist(
            delegate_state.with_(supervisor_metadata=meta)
        )

        # ── 6. Run delegate to completion ───────────────────────────
        delegate_state = self.run_agent_step(delegate_state)

        # If the delegate is WAITING (e.g. for a sub-deferral), loop
        # until terminal.  In D1 we only handle single-hop deferral;
        # sub-deferrals (A→B→C) will work naturally via recursive
        # defer_to_agent calls from within run_agent_step when the
        # defer_to tool is exposed to the LLM.
        max_iterations = 20
        iterations = 0
        while not delegate_state.is_terminal() and iterations < max_iterations:
            delegate_state = self.resume_agent(delegate_state)
            delegate_state = self.run_agent_step(delegate_state)
            iterations += 1

        # ── 7. Extract delegate response ────────────────────────────
        delegate_response = self.get_response(delegate_state)
        delegate_result_text = (
            delegate_response.reply if delegate_response else "No response from delegate"
        )
        delegate_success = (
            delegate_state.lifecycle_state == LifecycleState.COMPLETED
        )

        result_context = ContextBridge.build_delegate_result_context(
            delegate_id=target_agent_id,
            delegate_name=delegate_meta.identity.name,
            response_text=delegate_result_text,
            success=delegate_success,
        )

        # ── 8. Resume delegator with delegate result injected ───────
        state = self.resume_agent(state)
        meta = dict(state.supervisor_metadata)
        meta["deferral_result"] = {
            "delegate_id": target_agent_id,
            "delegate_name": delegate_meta.identity.name,
            "success": delegate_success,
            "response": delegate_result_text,
            "response_context": result_context,
        }
        state = self._persist(state.with_(supervisor_metadata=meta))

        return state

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

    # ------------------------------------------------------------------
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

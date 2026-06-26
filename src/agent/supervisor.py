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
import sqlite3
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
from src.agent.router import DEST_COUNCIL, DEST_RUNTIME, DEST_S4B, DEST_WORKFLOW, Route, route_message
from src.agent.selection import AgentSelectionStrategy
from src.agent.workflow import WorkflowEngine, WorkflowInstanceStore, WorkflowRegistry
from src.agent.workflow.engine import WorkflowExecutionState, WorkflowStatus
from src.agent.workflow.user_interaction import UserInteractionManager
from src.capabilities.patterns.pattern_registry import PatternRegistry
from src.agent.strategy_router import RouterOutcome, StrategyRouter
from src.agent.decomposition.orchestrator import DecompositionOrchestrator
from src.agent.interfaces.s2_planner import S2PlanDecomposer
from src.agent.types.decomposition import DecompositionPlan, DecompositionRequest, FanOutResult, MergeResult, SubtaskSpec
from src.capabilities.planner.todo_store import TodoStore
from src.platform.runtime.join_handle import JoinHandleState
from src.platform.runtime.job_store.job_store import JobStore

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
        council_registry: Optional[Any] = None,
        council_orchestrator: Optional[Any] = None,
        decomposer: Optional[S2PlanDecomposer] = None,
        decomposition_orchestrator: Optional[DecompositionOrchestrator] = None,
        job_store: Optional[JobStore] = None,
    ) -> None:
        self._registry = registry
        self._store = store
        self._submit_job = submit_job_callable
        self._decomposer = decomposer
        self._decomposition_orchestrator = decomposition_orchestrator
        self._job_store = job_store
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
        self._council_registry = council_registry
        self._council_orchestrator = council_orchestrator
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
            council_orchestrator=council_orchestrator,
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

    def _get_council_instructions(self, agent_meta) -> list[dict]:
        """Return council metadata for councils listed by the agent.

        Each entry includes council_id, name, description, member
        agent IDs, and the arbitrator — injected so the agent knows
        which councils it can deliberate with and how to invoke them.
        """
        if not self._council_registry:
            return []
        result: list[dict] = []
        for cid in agent_meta.councils:
            council = self._council_registry.get(cid)
            if council:
                result.append({
                    "council_id": council.council_id,
                    "name": council.name,
                    "description": council.description,
                    "members": list(council.member_agent_ids),
                    "arbitrator": council.arbitrator_agent_id,
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

            # D1.9: inject execute_todo_plan synthetic tool when the agent
            # uses the plan-with-todo pattern — fan-out/fan-in replaces manual
            # sequential execution of plan items.
            if ("plan_with_todo" in agent_meta.patterns
                    and self._decomposition_orchestrator is not None):
                tool_context.append(
                    self._build_execute_todo_plan_tool()
                )

            # C1: inject convene_council synthetic tool when the agent
            # has councils available for deliberation.
            if agent_meta.councils and self._council_registry:
                available = [
                    cid for cid in agent_meta.councils
                    if self._council_registry.has_council(cid)
                ]
                if available:
                    tool_context.append(
                        self._build_convene_council_tool(available)
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
                            "councils": self._get_council_instructions(agent_meta),
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

                # D1.9: intercept execute_todo_plan tool calls — execute
                # fan-out/fan-in in the Supervisor BEFORE ToolOrchestrator
                # processes other tools.
                if tool_calls:
                    _exec_calls = [
                        tc for tc in tool_calls
                        if isinstance(tc, dict) and tc.get("name", "") == "execute_todo_plan"
                        or hasattr(tc, "name") and getattr(tc, "name", "") == "execute_todo_plan"
                    ]
                    if _exec_calls:
                        for _tc in _exec_calls:
                            _args = _tc.get("arguments", _tc.get("args", {}))
                            if isinstance(_args, str):
                                _args = json.loads(_args)
                            _db_path = _args.get("db_path", "todo_plan.db")
                            _caller = state.agent_id
                            try:
                                _result = self.execute_todo_plan(
                                    _db_path,
                                    calling_agent_id=_caller,
                                )
                                _summary = _result.get("summary", "")[:2000]
                                _status = _result.get("status", "")
                                reply += (
                                    f"\n\n[Plan executed via fan-out/fan-in: "
                                    f"{_status} — {_summary}]"
                                )
                            except Exception as _exc:
                                reply += (
                                    f"\n\n[Todo plan execution failed: {_exc}]"
                                )
                        # Remove execute_todo_plan calls so ToolOrchestrator
                        # doesn't see them
                        tool_calls = [
                            tc for tc in tool_calls
                            if (
                                isinstance(tc, dict)
                                and tc.get("name", "") != "execute_todo_plan"
                            )
                            or (
                                hasattr(tc, "name")
                                and getattr(tc, "name", "") != "execute_todo_plan"
                            )
                        ]

                # C1: intercept convene_council tool calls — run council
                # deliberation and inject the outcome back into the
                # conversation so the calling agent can continue its work.
                # Uses the (potentially defer_to-filtered) tool_calls list.
                if tool_calls:
                    _council_calls = [
                        tc for tc in tool_calls
                        if isinstance(tc, dict) and tc.get("name", "") == "convene_council"
                        or hasattr(tc, "name") and getattr(tc, "name", "") == "convene_council"
                    ]
                    if _council_calls:
                        for _tc in _council_calls:
                            _args = _tc.get("arguments", _tc.get("args", {}))
                            if isinstance(_args, str):
                                _args = json.loads(_args)
                            _cid = _args.get("council_id", "")
                            _problem = _args.get("problem", "")
                            if _cid and _problem and self._council_registry:
                                _council_def = self._council_registry.get(_cid)
                                if _council_def and self._council_orchestrator:
                                    try:
                                        _outcome = self._council_orchestrator.deliberate(
                                            council_def=_council_def,
                                            problem=_problem,
                                            calling_agent_state=state,
                                        )
                                        reply += (
                                            f"\n\n**Council {_council_def.name} deliberation**\n"
                                            f"Decision: {_outcome.decision}\n"
                                            f"Confidence: {_outcome.confidence:.1%}"
                                        )
                                        if _outcome.dissent_notes:
                                            reply += f"\nDissent: {_outcome.dissent_notes}"
                                    except Exception as _exc:
                                        reply += (
                                            f"\n\n[Council deliberation failed: {_exc}]"
                                        )
                        # Remove convene_council calls so ToolOrchestrator
                        # doesn't see them
                        tool_calls = [
                            tc for tc in tool_calls
                            if (
                                isinstance(tc, dict)
                                and tc.get("name", "") != "convene_council"
                            )
                            or (
                                hasattr(tc, "name")
                                and getattr(tc, "name", "") != "convene_council"
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

                # Sprint 12b: todo items were created — execution is now
                # handled by the LLM calling execute_todo_plan after user
                # approval (Phase 3 of the plan-with-todo pattern).
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

        if route.destination == DEST_COUNCIL:
            council_id = route.payload.get("council_id", "")
            problem = route.payload.get("problem", input_text)

            if self._council_registry is None:
                new_errors.append({
                    "type": "council_not_configured",
                    "message": "Council route matched but no council registry configured",
                })
                return self._persist(state.with_(
                    lifecycle_state=LifecycleState.COMPLETED,
                    route_result=route,
                    errors=new_errors,
                    supervisor_metadata=meta,
                    _reason="Council registry not configured",
                    _details={"route_destination": route.destination},
                ))

            council_def = self._council_registry.get(council_id)
            if council_def is None:
                new_errors.append({
                    "type": "council_not_found",
                    "message": f"Council {council_id!r} not found in registry",
                })
                return self._persist(state.with_(
                    lifecycle_state=LifecycleState.COMPLETED,
                    route_result=route,
                    errors=new_errors,
                    supervisor_metadata=meta,
                    _reason=f"Council {council_id!r} not found",
                    _details={
                        "route_destination": route.destination,
                        "council_id": council_id,
                    },
                ))

            if self._council_orchestrator is None:
                new_errors.append({
                    "type": "council_orchestrator_not_configured",
                    "message": "Council route matched but no council orchestrator configured",
                })
                return self._persist(state.with_(
                    lifecycle_state=LifecycleState.COMPLETED,
                    route_result=route,
                    errors=new_errors,
                    supervisor_metadata=meta,
                    _reason="Council orchestrator not configured",
                    _details={"route_destination": route.destination},
                ))

            try:
                council_outcome = self._council_orchestrator.deliberate(
                    council_def=council_def,
                    problem=problem,
                    calling_agent_state=state,
                )
                reply = (
                    f"**Council {council_def.name} deliberation complete**\n\n"
                    f"**Decision:** {council_outcome.decision}\n\n"
                    f"**Confidence:** {council_outcome.confidence:.1%}\n\n"
                )
                if council_outcome.dissent_notes:
                    reply += f"**Dissent:** {council_outcome.dissent_notes}\n\n"

                return self._persist(state.with_(
                    lifecycle_state=LifecycleState.COMPLETED,
                    route_result=route,
                    final_response=AgentResponse(
                        reply=reply,
                        metadata={
                            "correlation_id": state.correlation_id,
                            "trace_id": state.trace_id,
                            "agent_id": state.agent_id,
                            "council_id": council_id,
                            "council_outcome": {
                                "decision": council_outcome.decision,
                                "confidence": council_outcome.confidence,
                                "member_count": len(council_outcome.member_analyses),
                            },
                        },
                    ),
                    supervisor_metadata=meta,
                    _reason="Council deliberation completed",
                    _details={"council_id": council_id},
                ))
            except Exception as exc:
                new_errors.append({
                    "type": "council_deliberation_error",
                    "message": f"Council deliberation failed: {exc}",
                })
                return self._persist(state.with_(
                    lifecycle_state=LifecycleState.FAILED,
                    route_result=route,
                    errors=new_errors,
                    supervisor_metadata=meta,
                    _reason=str(exc),
                    _details={
                        "route_destination": route.destination,
                        "council_id": council_id,
                    },
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

    # ── 5b. execute_todo_plan tool ────────────────────────────────────────

    @staticmethod
    def _build_execute_todo_plan_tool() -> dict:
        """Build a synthetic ``execute_todo_plan`` tool definition.

        Injected when the agent has ``plan_with_todo`` in its pattern list
        *and* a DecompositionOrchestrator is configured on the Supervisor.

        The LLM calls this after the user approves a plan.  The Supervisor
        intercepts the call, fans out all pending todos respecting
        dependencies, fans in results, and marks todos done/failed.
        """
        return {
            "type": "function",
            "function": {
                "name": "execute_todo_plan",
                "description": (
                    "Execute all pending todo items using fan-out/fan-in. "
                    "Call this AFTER the user approves the plan. "
                    "Items without dependencies run in parallel; sequential "
                    "chains are preserved. Results are merged automatically."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "db_path": {
                            "type": "string",
                            "description": (
                                "Path to the SQLite todo database "
                                "(the same db_path used when creating items)."
                            ),
                            "default": "todo_plan.db",
                        },
                    },
                },
            },
        }

    # ── 5c. convene_council tool ─────────────────────────────────────────

    @staticmethod
    def _build_convene_council_tool(available_councils: List[str]) -> dict:
        """Build a synthetic ``convene_council`` tool definition.

        Only injected when the agent has councils available and the
        council registry is configured.  The *council_id* parameter is
        constrained to an enum of the agent's registered councils.
        """
        return {
            "type": "function",
            "function": {
                "name": "convene_council",
                "description": (
                    "Convene a council of specialist agents to deliberate "
                    "on a difficult or high-stakes decision. Each council "
                    "member analyses the problem from their perspective, "
                    "challenges other members' reasoning, and an impartial "
                    "arbitrator synthesises a final decision. Use this when "
                    "you need diverse perspectives on a complex problem."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "council_id": {
                            "type": "string",
                            "description": "The ID of the council to convene.",
                            "enum": sorted(available_councils),
                        },
                        "problem": {
                            "type": "string",
                            "description": (
                                "The problem or decision to put before the "
                                "council. Be specific and include relevant "
                                "context so members can provide meaningful "
                                "analysis."
                            ),
                        },
                    },
                    "required": ["council_id", "problem"],
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
        skip_authorization: bool = False,
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
            ``defer_to`` list (unless *skip_authorization* is True) and
            the deferral graph must be acyclic (enforced at registration
            time).
        prompt:
            Natural-language instructions describing what the delegate
            should do.
        max_depth:
            Maximum deferral chain depth (default 3).  Each deferral
            increments the chain depth counter stored in
            ``supervisor_metadata["current_deferral_depth"]``.
        skip_authorization:
            Bypass the ``defer_to``-list check.  Used by the council
            orchestrator to invoke member agents systemically.

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
            If *target_agent_id* is not in the delegator's ``defer_to`` list
            and *skip_authorization* is False.
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
        if skip_authorization:
            # Bypass the defer_to-list check: lookup the target directly
            # via the registry so we still get metadata (name, etc.).
            delegate_meta = self._registry.get_agent(target_agent_id)
        else:
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

    # ── 5b. decompose_task ─────────────────────────────────────────────

    def decompose_task(
        self,
        state: AgentState,
        task: str,
        *,
        max_depth: int = 2,
        available_agents: list[str] | None = None,
        poll_interval_seconds: float = 0.5,
        poll_timeout_seconds: float = 1800.0,
    ) -> AgentState:
        """Fan-out a non-atomic task to N child agents, wait, then merge.

        Full lifecycle: **suspend** the parent → get decomposition plan →
        fan-out N child jobs → wait for JoinHandle → fan-in merge →
        **resume** the parent with merged results.

        The parent must be in RUNNING or WAITING state (i.e. active).

        After this call the parent resumes in RUNNING state with merged
        results in ``supervisor_metadata["decomposition_result"]``.

        Parameters
        ----------
        state:
            Current state of the parent agent (must be active).
        task:
            Natural-language description of the task to decompose.
        max_depth:
            Maximum decomposition depth (default 2).
        available_agents:
            Optional list of agent IDs that can serve as subtask targets.
            Defaults to all registered agents if not provided.
        poll_interval_seconds:
            Seconds between JoinHandle polls (default 0.5).
        poll_timeout_seconds:
            Maximum wall-clock seconds to wait for children (default 1800).

        Returns
        -------
        AgentState:
            Updated parent state in RUNNING with decomposition results
            in ``supervisor_metadata["decomposition_result"]``.
        """
        self._require_not_terminal(state)

        if not state.is_active():
            raise AgentNotActiveError(
                f"cannot decompose from agent {state.agent_id!r} in "
                f"state {state.lifecycle_state.value}; "
                f"expected RUNNING or WAITING"
            )

        # ── 1. Decompose via the planner protocol ──────────────────────
        decomposer = self._decomposer
        if decomposer is None:
            raise SupervisorError(
                "decompose_task requires a decomposer (S2PlanDecomposer); "
                "none was provided to the Supervisor constructor"
            )

        if available_agents is None:
            available_agents = [m.identity.agent_id for m in self._registry.list_agents()]

        request = DecompositionRequest(
            parent_task=task,
            parent_context=dict(state.supervisor_metadata),
            available_agents=available_agents,
            constraints={
                "max_depth": max_depth,
                "max_children": 8,
            },
        )
        plan = decomposer.decompose(request)

        if plan is None:
            # Task cannot be decomposed — treat as atomic, no-op.
            return state

        # ── 2. Fan-out via the orchestrator ────────────────────────────
        orchestrator = self._decomposition_orchestrator
        if orchestrator is None:
            raise SupervisorError(
                "decompose_task requires a DecompositionOrchestrator; "
                "none was provided to the Supervisor constructor"
            )

        fan_out_result: FanOutResult = orchestrator.fan_out(
            plan, parent_job_id=state.agent_id,
        )

        # ── 3. Suspend parent to AWAITING_CHILDREN ─────────────────────
        state = state.with_(
            lifecycle_state=LifecycleState.AWAITING_CHILDREN,
            _reason=f"Decomposing task (plan={plan.plan_id}, "
                    f"subtasks={len(plan.subtasks)})",
            _details={
                "plan_id": plan.plan_id,
                "subtask_count": len(plan.subtasks),
                "child_job_ids": fan_out_result.child_job_ids,
                "task_preview": task[:200],
            },
        )
        meta = dict(state.supervisor_metadata)
        meta["decomposition_fan_out"] = {
            "plan_id": plan.plan_id,
            "join_handle_id": fan_out_result.join_handle_id,
            "child_job_ids": fan_out_result.child_job_ids,
            "continuation_job_id": fan_out_result.continuation_job_id,
            "merge_strategy": plan.merge_strategy,
            "merge_agent_id": plan.merge_agent_id,
            "merge_prompt_template": plan.merge_prompt_template,
        }
        state = self._persist(
            state.with_(supervisor_metadata=meta)
        )

        # ── 4. Fan-in — poll until all children complete or timeout ────
        import time as _time
        deadline = _time.monotonic() + poll_timeout_seconds
        join_store = (
            orchestrator._join_store  # noqa: SLF001
        )
        # Ensure the worker pool is started so pool threads drain the
        # queue independently while we poll.
        pool = getattr(self, "_decomposition_worker_pool", None)
        if pool is not None and not pool.is_running:
            pool.start()

        while _time.monotonic() < deadline:
            handle = join_store.get(fan_out_result.join_handle_id)
            if handle is None:
                raise SupervisorError(
                    f"JoinHandle {fan_out_result.join_handle_id} "
                    f"disappeared during fan-in"
                )
            if handle.state == JoinHandleState.COMPLETED:
                break
            if handle.state == JoinHandleState.FAILED:
                state = self._persist(
                    state.with_(
                        lifecycle_state=LifecycleState.FAILED,
                        errors=[
                            *state.errors,
                            {
                                "type": "decomposition_failed",
                                "message": (
                                    f"JoinHandle {handle.join_handle_id} "
                                    f"entered FAILED state"
                                ),
                                "details": {
                                    "plan_id": plan.plan_id,
                                    "child_job_ids": (
                                        fan_out_result.child_job_ids
                                    ),
                                },
                            },
                        ],
                    )
                )
                return state
            _time.sleep(poll_interval_seconds)
        else:
            # Timeout reached
            orchestrator.cancel(plan.plan_id)
            state = self._persist(
                state.with_(
                    lifecycle_state=LifecycleState.FAILED,
                    errors=[
                        *state.errors,
                        {
                            "type": "decomposition_timeout",
                            "message": (
                                f"Fan-in timed out after "
                                f"{poll_timeout_seconds}s"
                            ),
                            "details": {
                                "plan_id": plan.plan_id,
                                "join_handle_id": (
                                    fan_out_result.join_handle_id
                                ),
                            },
                        },
                    ],
                )
            )
            return state

        # ── 5. Collect child results from JobStore ─────────────────────
        job_store = self._job_store
        child_results: dict[str, dict[str, Any]] = {}
        if job_store is not None:
            for subtask_id, job_id in zip(
                (s.id for s in plan.subtasks),
                fan_out_result.child_job_ids,
            ):
                child_job = job_store.get(job_id)
                if child_job is not None and child_job.result is not None:
                    child_results[subtask_id] = child_job.result

        # ── 6. Execute merge ───────────────────────────────────────────
        merged = orchestrator.fan_in(
            join_handle_id=fan_out_result.join_handle_id,
            child_results=child_results,
            parent_context={
                "task": task,
                "metadata": dict(state.supervisor_metadata),
            },
        )

        # ── 7. Resume parent with result injected ──────────────────────
        meta = dict(state.supervisor_metadata)
        meta["decomposition_result"] = {
            "output": merged.output,
            "strategy": merged.strategy,
            "selected": merged.selected,
            "satisfaction_gap": merged.satisfaction_gap,
            "child_summaries": merged.child_summaries,
            "child_job_ids": fan_out_result.child_job_ids,
        }
        state = self._persist(
            state.with_(
                lifecycle_state=LifecycleState.RUNNING,
                supervisor_metadata=meta,
            )
        )

        return state

    # ── parallelize ────────────────────────────────────────────────────

    def parallelize(
        self,
        items: list[tuple[str, str]],
        *,
        parent_task: str = "",
        merge_strategy: str = "concat",
    ) -> tuple[MergeResult, dict[str, dict[str, Any]]]:
        """Synchronously execute N items in parallel via decomposition.

        Unlike ``decompose_task()`` which uses the LLM decomposer to
        produce a plan, this method takes an explicit list of
        ``(agent_id, description)`` tuples and fans them all out at once.
        The calling agent/session is **not** suspended — this blocks
        until all items complete and returns the merged result plus raw
        per-agent outputs.

        Parameters
        ----------
        items:
            List of ``(agent_id, prompt)`` tuples to execute in parallel.
        parent_task:
            Optional label for the merge context (e.g. the council problem).
        merge_strategy:
            Merge strategy (default ``"concat"``).

        Returns
        -------
        tuple[MergeResult, dict[str, dict[str, Any]]]:
            ``(merged_result, agent_results)`` where ``agent_results``
            maps each agent_id → its job result dict (``{"output": …,
            "status": …, "done": True}``).
        """
        orchestrator = self._decomposition_orchestrator
        if orchestrator is None:
            raise RuntimeError(
                "parallelize requires a DecompositionOrchestrator; "
                "ensure decomposition is configured"
            )
        pool = getattr(self, "_decomposition_worker_pool", None)
        if pool is None:
            raise RuntimeError(
                "parallelize requires a decomposition worker pool; "
                "ensure _decomposition_worker_pool is late-bound"
            )
        if not pool.is_running:
            pool.start()

        parent_job_id = str(uuid.uuid4())
        return orchestrator.parallelize(
            parent_job_id=parent_job_id,
            items=items,
            job_store_get=self._job_store.get,
            parent_task=parent_task,
            merge_strategy=merge_strategy,
        )

    # ── 5c. execute_todo_plan (fan-out/fan-in from todo store) ─────────

    def execute_todo_plan(
        self,
        db_path: str,
        *,
        calling_agent_id: str = "default-agent",
        merge_strategy: str = "concat",
        poll_interval: float = 0.5,
        poll_timeout: float = 600.0,
    ) -> dict[str, Any]:
        """Execute all pending todos from *db_path* via fan-out/fan-in.

        This is the synthetic ``execute_todo_plan`` tool handler.  It opens
        the SQLite todo database, builds a ``DecompositionPlan`` from all
        ``pending`` / ``in_progress`` items, fans out subtasks (respecting
        dependency order), polls for completion, fans in results, and marks
        todos as done or failed.

        Parameters
        ----------
        db_path:
            Path to the SQLite todo store database.
        calling_agent_id:
            Fallback agent ID used when a ``TodoItem`` has no ``agent_id``.
        merge_strategy:
            Passed through to the orchestrator fan-in.
        poll_interval:
            Seconds between completion checks (default 0.5).
        poll_timeout:
            Maximum seconds to wait for completion (default 600).

        Returns
        -------
        dict:
            ``{"status": "succeeded"|"failed", "summary": str,
            "results": list[dict]}``.
        """
        orchestrator = self._decomposition_orchestrator
        if orchestrator is None:
            return {
                "status": "failed",
                "summary": "No DecompositionOrchestrator configured.",
                "results": [],
            }
        pool = getattr(self, "_decomposition_worker_pool", None)
        if pool is None:
            return {
                "status": "failed",
                "summary": "No decomposition worker pool configured.",
                "results": [],
            }
        if not pool.is_running:
            pool.start()
        from src.capabilities.planner.todo_store import TodoStore

        import time as _time

        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            store = TodoStore(conn)

            items = store.get_all()
            pending = [t for t in items if t.status in ("pending", "in_progress")]
            if not pending:
                return {
                    "status": "succeeded",
                    "summary": "No pending todos to execute.",
                    "results": [],
                }

            # ── build SubtaskSpec list ──────────────────────────────────
            subtasks: list[SubtaskSpec] = []
            for todo in pending:
                deps: list[str] = []
                # resolve dependency IDs — stored as short IDs in todo.depends_on
                if todo.depends_on:
                    for dep in todo.depends_on:
                        if dep in {t.id for t in pending}:
                            deps.append(dep)
                subtasks.append(
                    SubtaskSpec(
                        subtask_id=todo.id,
                        description=todo.description
                        or todo.title
                        or todo.id,
                        agent_id=todo.agent_id or calling_agent_id,
                        depends_on=deps,
                    )
                )

            plan = DecompositionPlan(
                parent_task_id=f"todo-{uuid.uuid4().hex[:8]}",
                subtasks=subtasks,
            )

            # ── fan-out ─────────────────────────────────────────────────
            fan_out_result = orchestrator.fan_out(
                parent_job_id=plan.parent_task_id,
                plan=plan,
            )
            if fan_out_result.status == "failed":
                return {
                    "status": "failed",
                    "summary": f"Fan-out failed: {fan_out_result.error or 'unknown'}",
                    "results": [],
                }

            # ── poll for completion ─────────────────────────────────────
            started = _time.time()
            join_handle = fan_out_result.join_handle
            if join_handle is None:
                return {
                    "status": "failed",
                    "summary": "Fan-out returned no join handle.",
                    "results": [],
                }

            while join_handle.state not in (
                JoinHandleState.SUCCEEDED,
                JoinHandleState.FAILED,
            ):
                if _time.time() - started > poll_timeout:
                    return {
                        "status": "failed",
                        "summary": f"Timed out after {poll_timeout}s.",
                        "results": [],
                    }
                _time.sleep(poll_interval)
                join_handle = orchestrator.get_join_handle(
                    plan.parent_task_id
                ) or join_handle

            # ── fan-in ──────────────────────────────────────────────────
            merge_result = orchestrator.fan_in(
                parent_job_id=plan.parent_task_id,
                merge_strategy=merge_strategy,
            )
            all_results: list[dict] = []
            for subtask in subtasks:
                child = plan.get_child(subtask.subtask_id)
                if child is not None:
                    all_results.append({
                        "subtask_id": subtask.subtask_id,
                        "status": child.status,
                        "output": child.output,
                        "error": child.error,
                    })

            # ── mark todos done/failed ──────────────────────────────────
            for r in all_results:
                if r["status"] == "succeeded":
                    store.mark_done(r["subtask_id"])
                elif r["status"] == "failed":
                    store.mark_failed(
                        r["subtask_id"],
                        error=str(r.get("error", "")),
                    )

            overall = "succeeded" if merge_result.status == "succeeded" else "failed"
            return {
                "status": overall,
                "summary": merge_result.merged_output or f"Plan {overall}.",
                "results": all_results,
            }
        except Exception as exc:
            return {
                "status": "failed",
                "summary": f"execute_todo_plan error: {exc}",
                "results": [],
            }
        finally:
            if conn is not None:
                conn.close()

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

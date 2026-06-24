"""
Phase 5.5 — Workflow Execution Engine (deterministic state machine)
==================================================================

The engine is a **pure graph navigator**.  It reads a ``WorkflowDefinition``
and returns ``StepOutcome`` values that tell the caller (the Agent Runtime
Supervisor) what to do next.

The engine does **not**:
- call LLMs
- submit platform jobs
- perform cognitive reasoning
- mutate external state

It only:
- navigates the workflow graph
- evaluates deterministic condition expressions
- tracks execution state

Step outcome types and caller responsibilities:

``llm_call``
    Supervisor calls ``call_runtime_backend()`` with the step config.
``tool_execute``
    Supervisor calls ``dispatch_route()`` with the step config.
``sub_workflow``
    Supervisor starts a new workflow instance.
``waiting_for_input``
    Supervisor pauses the agent (WAITING) until the user responds.
``continue``
    Supervisor calls ``step()`` again — the engine advanced to the next
    step automatically (used after deterministic transitions like
    conditions, or returned by ``resume_with_result`` /
    ``resume_with_input`` to signal the caller to loop back to
    ``step()``).
``completed``
    Workflow is done — Supervisor marks the agent COMPLETED.
``failed``
    Workflow failed — Supervisor marks the agent FAILED.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Literal, Optional, Tuple

from src.agent.workflow.registry import WorkflowRegistry
from src.agent.workflow.workflow_definition import END_TARGET


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class WorkflowStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


@dataclass
class WorkflowExecutionState:
    """Per-run state for a single workflow execution.

    The caller (Supervisor) owns this object — the engine receives it
    as input and returns a new copy for each transition.
    """

    execution_id: str
    workflow_id: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    current_step_id: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    step_results: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Outcome
# ---------------------------------------------------------------------------

OutcomeType = Literal[
    "llm_call",
    "tool_execute",
    "sub_workflow",
    "waiting_for_input",
    "continue",
    "completed",
    "failed",
    "timeout",
    "council_deliberate",
]


@dataclass
class StepOutcome:
    """Instruction from the engine to the caller after evaluating a step.

    The caller MUST dispatch based on ``type``:

    * ``llm_call`` / ``tool_execute`` — dispatch to Runtime / S4B
    * ``sub_workflow`` — start a new workflow run
    * ``waiting_for_input`` — pause the agent
    * ``continue`` — a deterministic transition occurred (condition);
      caller should call ``step()`` again immediately
    * ``completed`` / ``failed`` — agent lifecycle terminal

    The ``step_id`` field identifies which step produced this outcome.
    The caller MUST pass it back to ``resume_with_result()`` or
    ``fail_step()`` so the engine can record the result.
    """

    type: OutcomeType
    step_id: str = ""
    next_step_id: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    workflow_id: Optional[str] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class WorkflowEngine:
    """Stateless workflow execution engine.

    Takes a ``WorkflowRegistry`` and exposes pure functions that navigate
    the workflow graph.  The engine does **not** call LLMs or submit jobs
    — it returns ``StepOutcome`` for the caller to dispatch.

    All public methods are idempotent — calling them with the same state
    produces the same result.
    """

    def __init__(
        self,
        registry: WorkflowRegistry,
        *,
        pattern_registry: Any = None,
        council_registry: Any = None,
    ) -> None:
        self._registry = registry
        self._pattern_registry = pattern_registry
        self._council_registry = council_registry

    # ── Public API ─────────────────────────────────────────────────────

    def start_workflow(
        self,
        workflow_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> WorkflowExecutionState:
        """Create execution state at the workflow's start step.

        Args:
            workflow_id:
                Must be registered in the workflow registry.
            context:
                Optional initial shared context.

        Returns:
            New ``WorkflowExecutionState`` with ``status=RUNNING``
            and ``current_step_id`` set to the workflow's ``start_step``.

        Raises:
            ValueError: If the workflow is not registered.
        """
        defn = self._registry.get(workflow_id)
        if defn is None:
            raise ValueError(
                f"workflow {workflow_id!r} not found in registry"
            )
        return WorkflowExecutionState(
            execution_id=str(uuid.uuid4()),
            workflow_id=workflow_id,
            status=WorkflowStatus.RUNNING,
            current_step_id=defn.start_step,
            context=context or {},
        )

    def step(
        self,
        state: WorkflowExecutionState,
    ) -> Tuple[WorkflowExecutionState, StepOutcome]:
        """Evaluate the current step and advance to the next.

        Pure function — no side effects.  Returns ``(new_state, outcome)``
        where ``new_state.current_step_id`` is already advanced.

        Args:
            state: Current execution state.

        Returns:
            Tuple of ``(new_state, outcome)``.  The ``outcome.type`` tells
            the caller what action to take next.
        """
        # ── Terminal guard ──────────────────────────────────────────
        if state.status in (
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        ):
            return state, StepOutcome(
                type="completed" if state.status == WorkflowStatus.COMPLETED
                else "failed",
                error=state.error,
            )

        # ── No current step → completed ─────────────────────────────
        if state.current_step_id is None:
            return self._complete(state)

        # ── Resolve definition ──────────────────────────────────────
        defn = self._registry.get(state.workflow_id)
        if defn is None:
            return self._fail(
                state,
                f"workflow {state.workflow_id!r} not found in registry",
            )

        step = defn.steps.get(state.current_step_id)
        if step is None:
            return self._fail(
                state,
                f"current step {state.current_step_id!r} not found "
                f"in workflow {state.workflow_id!r}",
            )

        # ── Dispatch by step type ───────────────────────────────────
        handler = _STEP_HANDLERS.get(step.step_type)
        if handler is None:
            return self._fail(
                state,
                f"unknown step type {step.step_type!r} "
                f"in step {step.step_id!r}",
            )
        return handler(self, state, step, defn)

    def resume_with_input(
        self,
        state: WorkflowExecutionState,
        user_input: str,
    ) -> Tuple[WorkflowExecutionState, StepOutcome]:
        """Inject user input into context.

        The engine assumes ``current_step_id`` already points beyond
        the ``user_input`` step (set by the previous ``step()`` call).

        The caller (Supervisor) must call ``step()`` afterwards to
        evaluate the next step — this method stores the input only.

        Args:
            state: Execution state (should be WAITING_FOR_INPUT or RUNNING).
            user_input: The user's response text.

        Returns:
            ``(new_state, continue_outcome)`` — caller should loop
            back to ``step()``.
        """
        context = dict(state.context)
        context["_user_input"] = user_input
        resumed = _copy_state(state, status=WorkflowStatus.RUNNING, context=context)
        return resumed, StepOutcome(type="continue", step_id=state.current_step_id or "")

    def resume_with_result(
        self,
        state: WorkflowExecutionState,
        step_id: str,
        result: Any,
    ) -> Tuple[WorkflowExecutionState, StepOutcome]:
        """Record a step result.

        Called by the Supervisor when an ``llm_call``, ``tool_execute``,
        or ``sub_workflow`` step completes successfully.

        The caller (Supervisor) must call ``step()`` afterwards to
        evaluate the next step — this method stores the result only.

        Args:
            state: Execution state (current_step_id already advanced).
            step_id: The ID of the step that just completed.
            result: The result value to store in ``step_results``.

        Returns:
            ``(new_state, continue_outcome)`` — caller should loop
            back to ``step()``.
        """
        step_results = dict(state.step_results)
        step_results[step_id] = result
        context = dict(state.context)
        context["result"] = result
        # Extract a readable text from dict results (LLM responses)
        if isinstance(result, dict):
            context["last_output"] = str(result.get("message") or result)
        else:
            context["last_output"] = str(result)
        resumed = _copy_state(
            state,
            status=WorkflowStatus.RUNNING,
            context=context,
            step_results=step_results,
        )
        return resumed, StepOutcome(type="continue", step_id=step_id)

    def fail_step(
        self,
        state: WorkflowExecutionState,
        step_id: str,
        error: str,
    ) -> Tuple[WorkflowExecutionState, StepOutcome]:
        """Record a step failure and follow ``on_failure`` if defined.

        Args:
            state: Execution state.
            step_id: The ID of the step that failed.
            error: Error description.

        Returns:
            If the step defines ``on_failure``, the engine advances to
            that step and returns ``(state, outcome)``.
            Otherwise the workflow is marked FAILED.
        """
        step_results = dict(state.step_results)
        step_results[step_id] = {"error": error, "status": "failed"}

        defn = self._registry.get(state.workflow_id)
        if defn is None:
            return self._fail(_copy_state(state, step_results=step_results), error)

        step = defn.steps.get(step_id)
        if step is None or "on_failure" not in step.transitions:
            return self._fail(_copy_state(state, step_results=step_results), error)

        target = step.transitions["on_failure"]
        if target == END_TARGET:
            completed = _copy_state(
                state,
                status=WorkflowStatus.COMPLETED,
                current_step_id=None,
                step_results=step_results,
            )
            return completed, StepOutcome(type="completed")

        advanced = _copy_state(
            state,
            status=WorkflowStatus.RUNNING,
            current_step_id=target,
            step_results=step_results,
        )
        return advanced, StepOutcome(type="continue", next_step_id=target)

    def cancel(
        self,
        state: WorkflowExecutionState,
    ) -> WorkflowExecutionState:
        """Cancel a workflow execution.

        Args:
            state: Current execution state.

        Returns:
            New state with ``status=CANCELLED``.
        """
        return _copy_state(state, status=WorkflowStatus.CANCELLED)

    def handle_timeout(
        self,
        state: WorkflowExecutionState,
        step_id: str,
    ) -> Tuple[WorkflowExecutionState, StepOutcome]:
        """Handle a timeout on a ``user_input`` step.

        Records the timeout in ``step_results`` and follows the step's
        ``on_failure`` transition if one is defined, otherwise marks the
        workflow as FAILED.

        Args:
            state: Execution state (should be WAITING_FOR_INPUT).
            step_id: The ID of the step that timed out.

        Returns:
            ``(new_state, outcome)`` — if the step defines an
            ``on_failure`` transition, advances to that step; otherwise
            the workflow is marked FAILED with a timeout error.
        """
        error = f"Step {step_id!r} timed out waiting for user input"
        step_results = dict(state.step_results)
        step_results[step_id] = {"error": error, "status": "timeout"}

        defn = self._registry.get(state.workflow_id)
        if defn is None:
            return self._fail(_copy_state(state, step_results=step_results), error)

        step = defn.steps.get(step_id)
        if step is None or "on_failure" not in step.transitions:
            return self._fail(_copy_state(state, step_results=step_results), error)

        target = step.transitions["on_failure"]
        if target == END_TARGET:
            completed = _copy_state(
                state,
                status=WorkflowStatus.COMPLETED,
                current_step_id=None,
                step_results=step_results,
            )
            return completed, StepOutcome(type="completed")

        advanced = _copy_state(
            state,
            status=WorkflowStatus.RUNNING,
            current_step_id=target,
            step_results=step_results,
        )
        return advanced, StepOutcome(type="continue", next_step_id=target)

    # ── Internal helpers ──────────────────────────────────────────────

    def _advance(
        self,
        state: WorkflowExecutionState,
        step: Any,
        outcome: StepOutcome,
    ) -> Tuple[WorkflowExecutionState, StepOutcome]:
        """Follow ``on_success`` transition and advance current_step_id.

        Does **not** complete the workflow when the target is ``__end__`` —
        the caller (``_run_workflow_loop``) decides whether the step is
        blocking (e.g. ``tool_execute`` → WAITING) or terminal.
        """
        target = step.transitions.get("on_success", END_TARGET)
        new_id = None if target == END_TARGET else target
        new_state = _copy_state(state, current_step_id=new_id)
        return new_state, outcome

    def _advance_on(
        self,
        state: WorkflowExecutionState,
        step: Any,
        transition_key: str,
        outcome: StepOutcome,
    ) -> Tuple[WorkflowExecutionState, StepOutcome]:
        """Follow a specific transition key and advance current_step_id.

        Does **not** complete the workflow when the target is ``__end__`` —
        same contract as ``_advance``.
        """
        target = step.transitions.get(transition_key, END_TARGET)
        new_id = None if target == END_TARGET else target
        new_state = _copy_state(state, current_step_id=new_id)
        return new_state, outcome

    def _complete(
        self,
        state: WorkflowExecutionState,
    ) -> Tuple[WorkflowExecutionState, StepOutcome]:
        """Mark the workflow as completed."""
        new_state = _copy_state(
            state,
            status=WorkflowStatus.COMPLETED,
            current_step_id=None,
        )
        return new_state, StepOutcome(type="completed")

    def _fail(
        self,
        state: WorkflowExecutionState,
        error: str,
    ) -> Tuple[WorkflowExecutionState, StepOutcome]:
        """Mark the workflow as failed."""
        new_state = _copy_state(state, status=WorkflowStatus.FAILED, error=error)
        return new_state, StepOutcome(type="failed", error=error)


# ── Step-type handlers ────────────────────────────────────────────────


def _handle_llm_call(
    engine: WorkflowEngine,
    state: WorkflowExecutionState,
    step: Any,
    defn: Any,
) -> Tuple[WorkflowExecutionState, StepOutcome]:
    return engine._advance(
        state,
        step,
        StepOutcome(type="llm_call", step_id=step.step_id, config=step.config),
    )


def _handle_tool_execute(
    engine: WorkflowEngine,
    state: WorkflowExecutionState,
    step: Any,
    defn: Any,
) -> Tuple[WorkflowExecutionState, StepOutcome]:
    return engine._advance(
        state,
        step,
        StepOutcome(type="tool_execute", step_id=step.step_id, config=step.config),
    )


def _handle_sub_workflow(
    engine: WorkflowEngine,
    state: WorkflowExecutionState,
    step: Any,
    defn: Any,
) -> Tuple[WorkflowExecutionState, StepOutcome]:
    sub_wf_id = step.config.get("workflow_id")
    if sub_wf_id is None:
        return engine._fail(
            state,
            f"sub_workflow step {step.step_id!r} missing config.workflow_id",
        )
    return engine._advance(
        state,
        step,
        StepOutcome(
            type="sub_workflow",
            step_id=step.step_id,
            workflow_id=sub_wf_id,
            config=step.config,
        ),
    )


def _handle_apply_pattern(
    engine: WorkflowEngine,
    state: WorkflowExecutionState,
    step: Any,
    defn: Any,
) -> Tuple[WorkflowExecutionState, StepOutcome]:
    """Resolve pattern instructions and emit an enriched llm_call outcome.

    Looks up the pattern by ``config.pattern_id`` in the engine's
    ``_pattern_registry``, injects the pattern's instructions into the
    step config, and emits an ``llm_call`` outcome so the invoker
    routes it to the LLM with pattern guidance.
    """
    pattern_id = step.config.get("pattern_id")
    if not pattern_id:
        return engine._fail(
            state,
            f"apply_pattern step {step.step_id!r} missing config.pattern_id",
        )

    pattern_registry = engine._pattern_registry
    if pattern_registry is None:
        return engine._fail(
            state,
            f"apply_pattern step {step.step_id!r}: no pattern_registry configured",
        )

    pattern = pattern_registry.get(pattern_id)
    if pattern is None:
        return engine._fail(
            state,
            f"apply_pattern step {step.step_id!r}: "
            f"pattern {pattern_id!r} not found in registry",
        )

    # Enrich config with pattern instructions for the LLM
    enriched_config = dict(step.config)
    enriched_config["pattern_instructions"] = [{
        "pattern_id": pattern.pattern_id,
        "name": pattern.name,
        "instructions": pattern.instructions,
    }]

    return engine._advance(
        state,
        step,
        StepOutcome(
            type="llm_call",
            step_id=step.step_id,
            config=enriched_config,
        ),
    )


def _handle_user_input(
    engine: WorkflowEngine,
    state: WorkflowExecutionState,
    step: Any,
    defn: Any,
) -> Tuple[WorkflowExecutionState, StepOutcome]:
    # Advance past the user_input step so that resume_with_input
    # evaluates the *next* step rather than re-entering this one.
    target = step.transitions.get("on_success")
    if target is None or target == END_TARGET:
        target_state = _copy_state(
            state,
            status=WorkflowStatus.WAITING_FOR_INPUT,
            current_step_id=None,
        )
    else:
        target_state = _copy_state(
            state,
            status=WorkflowStatus.WAITING_FOR_INPUT,
            current_step_id=target,
        )

    return target_state, StepOutcome(
        type="waiting_for_input",
        step_id=step.step_id,
        config=step.config,
    )


def _handle_condition(
    engine: WorkflowEngine,
    state: WorkflowExecutionState,
    step: Any,
    defn: Any,
) -> Tuple[WorkflowExecutionState, StepOutcome]:
    expression = step.config.get("expression", "True")
    try:
        result = _evaluate_expression(expression, state.context)
    except Exception as exc:
        return engine._fail(
            state,
            f"condition evaluation failed in step {step.step_id!r}: {exc}",
        )

    transition_key = "on_success" if result else "on_failure"
    return engine._advance_on(
        state,
        step,
        transition_key,
        StepOutcome(
            type="continue",
            step_id=step.step_id,
            next_step_id=step.transitions.get(transition_key, END_TARGET),
        ),
    )


def _handle_council_deliberate(
    engine: WorkflowEngine,
    state: WorkflowExecutionState,
    step: Any,
    defn: Any,
) -> Tuple[WorkflowExecutionState, StepOutcome]:
    """Handle a ``council_deliberate`` step.

    Validates that the council exists in the registry, then returns a
    ``council_deliberate`` outcome for the invoker to dispatch to the
    ``CouncilOrchestrator``.
    """
    council_id = step.config.get("council_id")
    if not council_id:
        return engine._fail(
            state,
            f"council_deliberate step {step.step_id!r} missing config.council_id",
        )

    if engine._council_registry is None:
        return engine._fail(
            state,
            f"council_deliberate step {step.step_id!r}: no council_registry configured",
        )

    council = engine._council_registry.get(council_id)
    if council is None:
        return engine._fail(
            state,
            f"council_deliberate step {step.step_id!r}: "
            f"council {council_id!r} not found in registry",
        )

    problem = step.config.get("problem") or state.context.get("problem", "")

    return engine._advance(
        state,
        step,
        StepOutcome(
            type="council_deliberate",
            step_id=step.step_id,
            config={
                "council_id": council_id,
                "problem": problem,
            },
        ),
    )


# ── Handler registry ──────────────────────────────────────────────────

_STEP_HANDLERS = {
    "llm_call": _handle_llm_call,
    "tool_execute": _handle_tool_execute,
    "sub_workflow": _handle_sub_workflow,
    "user_input": _handle_user_input,
    "condition": _handle_condition,
    "apply_pattern": _handle_apply_pattern,
    "council_deliberate": _handle_council_deliberate,
}


# ── Helpers ───────────────────────────────────────────────────────────


def _copy_state(
    state: WorkflowExecutionState,
    **overrides: Any,
) -> WorkflowExecutionState:
    """Create a new ``WorkflowExecutionState`` with selective overrides.

    Deep-copies ``context`` and ``step_results`` to keep the engine
    pure (no mutation of caller-owned state).
    """
    return WorkflowExecutionState(
        execution_id=overrides.pop("execution_id", state.execution_id),
        workflow_id=overrides.pop("workflow_id", state.workflow_id),
        status=overrides.pop("status", state.status),
        current_step_id=overrides.pop("current_step_id", state.current_step_id),
        context=overrides.pop("context", dict(state.context)),
        step_results=overrides.pop("step_results", dict(state.step_results)),
        error=overrides.pop("error", state.error),
    )


def _evaluate_expression(expression: str, context: dict) -> bool:
    """Safely evaluate a Python expression against a context dict.

    Only safe built-ins are exposed — no IO, no imports, no attribute
    access on arbitrary objects.
    """
    allowed_builtins: Dict[str, Any] = {
        "len": len,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
        "isinstance": isinstance,
    }
    result = eval(
        expression,
        {"__builtins__": allowed_builtins},
        {"context": context},
    )
    return bool(result)

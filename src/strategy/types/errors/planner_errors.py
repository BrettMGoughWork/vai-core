"""
Phase 3.21.3 — Planner Error Semantics
========================================

Strongly-typed exception hierarchy for planner-level failures.

All types inherit from both PlannerError and AgentError, making them:
  - raisable/catchable Python exceptions
  - planner-compatible via the AgentError interface
  - LLM-parsable through clear names and retryable semantics
  - integrated with map_error_to_recovery() for consistent handling

Hierarchy
---------
PlannerError (base)
├── Category A: Plan Validity
│   ├── PlanInvalid                 retryable=False  (plan is structurally impossible)
│   ├── PlanAmbiguous               retryable=False  (needs clarification before replan)
│   └── PlanMissingCapabilities     retryable=False  (missing primitives/skills)
├── Category B: Safety & Governance
│   └── PlanUnsafe                  retryable=False  (violates safety rules)
├── Category C: Execution Outcome
│   ├── PlanExecutionFailed         retryable=maybe  (runtime step failure)
│   └── PlanDegraded                retryable=True   (fallback path used; partial success)

Recovery Mapping
----------------
PlanInvalid             → REPLAN
PlanAmbiguous           → CLARIFY
PlanMissingCapabilities → REPLAN
PlanUnsafe              → ESCALATE
PlanExecutionFailed     → RETRY (if retryable) else REPLAN
PlanDegraded            → RETRY
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.strategy.types.errors.AgentError import AgentError


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class PlannerError(AgentError, Exception):
    """
    Base class for all planner-level errors.

    Carries plan_id for traceability and a retryable flag that controls
    whether the executor may retry the triggering operation.

    Parameters
    ----------
    message:
        Human-readable description of the planning failure.
    plan_id:
        Optional identifier for the plan that failed (for traceability).
    retryable:
        Whether the error condition may resolve with a retry or replan.
        Subclasses set a sensible default; callers may override.
    context:
        Optional arbitrary context dict for planner/LLM consumption.
    """

    _DEFAULT_RETRYABLE: bool = False

    def __init__(
        self,
        message: str,
        plan_id: str | None = None,
        retryable: bool | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        retryable_value = (
            retryable if retryable is not None else self._DEFAULT_RETRYABLE
        )
        details: dict[str, Any] = dict(context or {})
        if plan_id is not None:
            details["plan_id"] = plan_id
        details["retryable"] = retryable_value
        AgentError.__init__(
            self,
            type=type(self).__name__,
            message=message,
            details=details,
            timestamp=datetime.now(timezone.utc).isoformat(),
            recoverable=retryable_value,
        )
        Exception.__init__(self, message)
        self._retryable = retryable_value
        self._plan_id = plan_id

    @property
    def retryable(self) -> bool:
        return self._retryable

    @property
    def plan_id(self) -> str | None:
        return self._plan_id

    @property
    def context(self) -> dict[str, Any]:
        """Alias for details — provides consistent API with PrimitiveError."""
        return self.details

    def __str__(self) -> str:
        return f"[{self.__class__.__name__}] {self.message}"


# ---------------------------------------------------------------------------
# Category A: Plan Validity
# ---------------------------------------------------------------------------

class PlanInvalid(PlannerError):
    """
    The plan is structurally impossible to execute.

    Definition:
        The generated or received plan cannot be executed as-is — it
        references non-existent steps, has circular dependencies, contains
        incompatible step orderings, or violates structural invariants.

    When to Use:
        Raise when plan validation determines the plan cannot run at all,
        regardless of runtime state. Not for missing capabilities (use
        PlanMissingCapabilities) or safety violations (use PlanUnsafe).

    Typical Causes:
        - Circular step dependencies
        - Steps that reference undefined output bindings
        - Schema mismatch between step output and next step input
        - Plan produced by LLM that fails structural validation

    Planner Handling:
        REPLAN — the plan must be regenerated with corrected constraints.
        Optionally include the validation errors in the new planning context.

    Plan Revision:
        Implies the plan was wrong, not the primitives. The planner should
        add the structural error as a negative example when replanning.
    """

    _DEFAULT_RETRYABLE = False


class PlanAmbiguous(PlannerError):
    """
    The plan's intent is unclear and cannot be safely inferred.

    Definition:
        The goal or one or more plan steps have ambiguous meaning that
        would require the planner to guess — and guessing risks incorrect
        execution or user dissatisfaction.

    When to Use:
        Raise when the planner cannot determine intent with sufficient
        confidence. Prefer this over silent best-guess execution.

    Typical Causes:
        - Underspecified goal (e.g. "update the file" — which file?)
        - Conflicting constraints in the user request
        - Step parameters that could be interpreted multiple ways
        - Missing required context (e.g. target environment unknown)

    Planner Handling:
        CLARIFY — ask the user for the missing information before replanning.

    Plan Revision:
        Implies user clarification is needed. Do not replan until clarification
        is received. The clarified response should be added to planning context.
    """

    _DEFAULT_RETRYABLE = False


class PlanMissingCapabilities(PlannerError):
    """
    The plan requires primitives or skills that are not registered.

    Definition:
        One or more steps in the plan reference capabilities (primitives
        or skills) that do not exist in the capability registry at execution
        time.

    When to Use:
        Raise during plan validation when referenced capabilities cannot
        be resolved. Distinct from PlanInvalid (structural) — this is a
        capability graph gap.

    Typical Causes:
        - Skill was unloaded or not yet installed
        - Plugin providing the capability was removed
        - Plan was generated for a different capability set
        - Agent-authored skill not yet registered

    Planner Handling:
        REPLAN — regenerate without the missing capabilities, or propose
        a new skill to fill the gap (Stratum 4 / skill authoring).

    Plan Revision:
        Implies missing capabilities. The planner should note which
        capabilities are absent and either replan without them or trigger
        skill creation to fill the gap.
    """

    _DEFAULT_RETRYABLE = False

    def __init__(
        self,
        message: str,
        plan_id: str | None = None,
        missing_capabilities: tuple[str, ...] = (),
        retryable: bool | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        ctx = dict(context or {})
        if missing_capabilities:
            ctx["missing_capabilities"] = list(missing_capabilities)
        super().__init__(message, plan_id=plan_id, retryable=retryable, context=ctx)
        self._missing_capabilities = missing_capabilities

    @property
    def missing_capabilities(self) -> tuple[str, ...]:
        return self._missing_capabilities


# ---------------------------------------------------------------------------
# Category B: Safety & Governance
# ---------------------------------------------------------------------------

class PlanUnsafe(PlannerError):
    """
    The plan violates safety or governance rules.

    Definition:
        The plan or one of its steps has been blocked by the safety layer
        because it would perform an action that is forbidden, dangerous,
        or outside the agent's permitted scope.

    When to Use:
        Raise when safety policy evaluation (not structural validation)
        determines the plan must not proceed.

    Typical Causes:
        - Step attempts to delete system-critical files
        - Plan exceeds allowed side-effect budget
        - Governance rule blocks a required primitive
        - Privilege escalation detected in plan path

    Planner Handling:
        ESCALATE — safety violations require human review. Do not silently
        replan around safety blocks; surface them to the operator.

    Plan Revision:
        Implies the plan was unsafe, not impossible. After escalation, if
        the operator approves a modified scope, the planner may regenerate
        with explicit safety exceptions noted in context.
    """

    _DEFAULT_RETRYABLE = False

    def __init__(
        self,
        message: str,
        plan_id: str | None = None,
        violated_rule: str | None = None,
        retryable: bool | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        ctx = dict(context or {})
        if violated_rule is not None:
            ctx["violated_rule"] = violated_rule
        super().__init__(message, plan_id=plan_id, retryable=retryable, context=ctx)
        self._violated_rule = violated_rule

    @property
    def violated_rule(self) -> str | None:
        return self._violated_rule


# ---------------------------------------------------------------------------
# Category C: Execution Outcome
# ---------------------------------------------------------------------------

class PlanExecutionFailed(PlannerError):
    """
    A plan step failed at runtime.

    Definition:
        One or more plan steps raised an error during execution. The plan
        was valid and safe, but execution could not complete successfully.

    When to Use:
        Raise after a primitive or skill execution failure that the executor
        could not recover from internally (after exhausting its own retry
        policy).

    Typical Causes:
        - Network failure during a critical step
        - External service returned unexpected error
        - PrimitiveNonRetryableError propagated up from executor
        - Timeout exceeded at the plan level (not step level)

    Planner Handling:
        RETRY if retryable=True (e.g. transient failure, worth one more attempt).
        REPLAN if retryable=False (e.g. permanent failure; need alternative approach).

    Plan Revision:
        If the failing step is the only path, the planner must find an
        alternative route. If the primitive is unstable, consider flagging
        it as unreliable in project memory.
    """

    _DEFAULT_RETRYABLE = True

    def __init__(
        self,
        message: str,
        plan_id: str | None = None,
        failed_step: str | None = None,
        retryable: bool | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        ctx = dict(context or {})
        if failed_step is not None:
            ctx["failed_step"] = failed_step
        super().__init__(message, plan_id=plan_id, retryable=retryable, context=ctx)
        self._failed_step = failed_step

    @property
    def failed_step(self) -> str | None:
        return self._failed_step


class PlanDegraded(PlannerError):
    """
    Plan completed via a fallback path; the primary path was unavailable.

    Definition:
        Execution completed, but not via the primary plan path. A fallback
        skill, degraded mode, or alternative route was used. The result may
        be lower quality or less complete than intended.

    When to Use:
        Raise (or log as advisory) when the executor reports successful
        completion but via a non-preferred path. The planner should be
        aware so it can decide whether to retry with the primary path or
        accept the degraded result.

    Typical Causes:
        - Primary skill unavailable; fallback skill used
        - Step skipped due to non-critical failure
        - Partial data used because full data was unavailable
        - Result produced by less capable/accurate primitive

    Planner Handling:
        RETRY — attempt the primary path again (e.g. after a transient issue
        is resolved). If retry budget is exhausted, accept and note in memory.

    Plan Revision:
        Does not imply the plan was wrong. The planner may note the degradation
        in project memory so future plans prefer the fallback proactively if
        the primary path is unreliable.
    """

    _DEFAULT_RETRYABLE = True

    def __init__(
        self,
        message: str,
        plan_id: str | None = None,
        fallback_used: str | None = None,
        retryable: bool | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        ctx = dict(context or {})
        if fallback_used is not None:
            ctx["fallback_used"] = fallback_used
        super().__init__(message, plan_id=plan_id, retryable=retryable, context=ctx)
        self._fallback_used = fallback_used

    @property
    def fallback_used(self) -> str | None:
        return self._fallback_used


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

ALL_PLANNER_ERROR_TYPES: tuple[type[PlannerError], ...] = (
    PlanInvalid,
    PlanAmbiguous,
    PlanMissingCapabilities,
    PlanUnsafe,
    PlanExecutionFailed,
    PlanDegraded,
)

"""
Error Recovery Semantics Layer - Pure mapping from AgentError to RecoveryAction.

This module defines deterministic recovery semantics for each error type.
It is a pure mapping layer with NO side effects, NO retries, and NO planner calls.
The actual execution of recovery actions is handled by Phase 2.3 (Recovery Execution).
"""

from enum import Enum

from .AgentError import AgentError
from src.domain._markers import deadcode_ignore
from .primitive_errors import (
    PrimitiveError,
    PrimitiveExecutionError,
    PrimitiveTimeout,
    PrimitiveRetryableError,
    PrimitiveNonRetryableError,
    PrimitiveSideEffectError,
    PrimitiveValidationError,
    PrimitiveContractError,
    PrimitivePrivilegeError,
    PrimitiveEnvironmentError,
    PrimitiveDependencyError,
    PrimitiveNotFound,
)
from .planner_errors import (
    PlannerError,
    PlanInvalid,
    PlanAmbiguous,
    PlanMissingCapabilities,
    PlanUnsafe,
    PlanExecutionFailed,
    PlanDegraded,
)


class RecoveryAction(Enum):
    """
    Deterministic set of recovery actions for agent runtime errors.

    Each action represents a high-level response strategy that will be
    executed by the recovery execution layer (Phase 2.3).
    """

    RETRY = "retry"
    """Attempt the same operation again (typically with backoff)."""

    REPLAN = "replan"
    """Abort current plan and generate a new one with revised constraints."""

    ROLLBACK = "rollback"
    """Restore previous known-good state and restart from checkpoint."""

    ESCALATE = "escalate"
    """Escalate to human operator or higher authority for decision."""

    CLARIFY = "clarify"
    """Request clarification or additional context from user/environment."""


def map_error_to_recovery(error: AgentError) -> RecoveryAction:
    """
    Pure mapping function from AgentError to RecoveryAction.

    This function contains NO side effects and NO execution logic.
    It determines the appropriate recovery action based solely on the error type.
    The actual execution of the recovery action is delegated to Phase 2.3.

    Mapping rationale:
        - PlanningError → REPLAN: Planning failed; need to replan with revised goals/constraints
        - MappingError → REPLAN: Skill mapping failed; replan with different goals or constraints
        - ExecutionError → RETRY: Skill execution failed; retry (possibly with different skills)
        - StateError → ROLLBACK: State corrupted; rollback to last known-good checkpoint
        - ConfidenceError → CLARIFY: Decision confidence too low; request clarification
        - GovernanceError → ESCALATE: Policy violation; escalate for human review
        - SemanticError → CLARIFY: Interpretation unclear; request clarification

    Args:
        error: An AgentError instance to map to a recovery action

    Returns:
        RecoveryAction: The appropriate recovery action for this error type

    Raises:
        ValueError: If the error type is not recognized (defensive check)
    """
    error_type = error.type

    if error_type == "PlanningError":
        return RecoveryAction.REPLAN

    elif error_type == "MappingError":
        return RecoveryAction.REPLAN

    elif error_type == "ExecutionError":
        return RecoveryAction.RETRY

    elif error_type == "StateError":
        return RecoveryAction.ROLLBACK

    elif error_type == "ConfidenceError":
        return RecoveryAction.CLARIFY

    elif error_type == "GovernanceError":
        return RecoveryAction.ESCALATE

    elif error_type == "SemanticError":
        return RecoveryAction.CLARIFY

    # --- Primitive Error Taxonomy (Phase 3.21.1) ---
    # Dispatch on isinstance first (PrimitiveError subclasses carry retryable flag).
    elif isinstance(error, PrimitiveError):
        return _map_primitive_error(error)

    # --- Planner Error Semantics (Phase 3.21.3) ---
    elif isinstance(error, PlannerError):
        return _map_planner_error(error)

    else:
        raise ValueError(f"Unknown error type: {error_type}")


# ---------------------------------------------------------------------------
# Primitive error recovery mapping
# ---------------------------------------------------------------------------

_PRIMITIVE_RETRY_TYPES = (
    PrimitiveRetryableError,
    PrimitiveTimeout,
    PrimitiveDependencyError,
)

_PRIMITIVE_REPLAN_TYPES = (
    PrimitiveNonRetryableError,
    PrimitiveValidationError,
    PrimitiveContractError,
    PrimitiveNotFound,
)

_PRIMITIVE_ESCALATE_TYPES = (
    PrimitiveSideEffectError,
    PrimitivePrivilegeError,
    PrimitiveEnvironmentError,
)


def _map_primitive_error(error: PrimitiveError) -> RecoveryAction:
    """
    Pure mapping from a PrimitiveError subtype to a RecoveryAction.

    Mapping rationale:
      - PrimitiveRetryableError / PrimitiveTimeout / PrimitiveDependencyError
            → RETRY   (transient; retry with backoff)
      - PrimitiveNonRetryableError / PrimitiveValidationError /
        PrimitiveContractError / PrimitiveNotFound
            → REPLAN  (plan step was wrong; rewrite required)
      - PrimitiveSideEffectError / PrimitivePrivilegeError /
        PrimitiveEnvironmentError
            → ESCALATE (safety/environment issue; operator required)
      - PrimitiveExecutionError (generic catch-all)
            → RETRY if retryable=True, else REPLAN
    """
    if isinstance(error, _PRIMITIVE_RETRY_TYPES):
        return RecoveryAction.RETRY
    if isinstance(error, _PRIMITIVE_REPLAN_TYPES):
        return RecoveryAction.REPLAN
    if isinstance(error, _PRIMITIVE_ESCALATE_TYPES):
        return RecoveryAction.ESCALATE
    # PrimitiveExecutionError or any future subclass: defer to retryable flag
    if error.retryable:
        return RecoveryAction.RETRY
    return RecoveryAction.REPLAN


# ---------------------------------------------------------------------------
# Planner error recovery mapping
# ---------------------------------------------------------------------------

_PLANNER_REPLAN_TYPES = (
    PlanInvalid,
    PlanMissingCapabilities,
)

_PLANNER_CLARIFY_TYPES = (
    PlanAmbiguous,
)

_PLANNER_ESCALATE_TYPES = (
    PlanUnsafe,
)

_PLANNER_RETRY_TYPES = (
    PlanDegraded,
)


def _map_planner_error(error: PlannerError) -> RecoveryAction:
    """
    Pure mapping from a PlannerError subtype to a RecoveryAction.

    Mapping rationale:
      - PlanInvalid / PlanMissingCapabilities
            → REPLAN  (plan was wrong or incomplete; regenerate)
      - PlanAmbiguous
            → CLARIFY (ask user before replanning)
      - PlanUnsafe
            → ESCALATE (safety violation; requires human review)
      - PlanDegraded
            → RETRY   (primary path may recover; try again)
      - PlanExecutionFailed
            → RETRY if retryable=True, else REPLAN
    """
    if isinstance(error, _PLANNER_REPLAN_TYPES):
        return RecoveryAction.REPLAN
    if isinstance(error, _PLANNER_CLARIFY_TYPES):
        return RecoveryAction.CLARIFY
    if isinstance(error, _PLANNER_ESCALATE_TYPES):
        return RecoveryAction.ESCALATE
    if isinstance(error, _PLANNER_RETRY_TYPES):
        return RecoveryAction.RETRY
    # PlanExecutionFailed or any future subclass: defer to retryable flag
    if error.retryable:
        return RecoveryAction.RETRY
    return RecoveryAction.REPLAN

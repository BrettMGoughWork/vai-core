"""
Error Types Layer - Strongly typed error taxonomy for agent runtime.

This module defines a deterministic, closed error taxonomy used across
the planner, mapper, executor, and state manager. Each error type represents
a distinct class of failures with explicit recovery semantics.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class AgentError:
    """
    Base error dataclass for all agent runtime errors.

    Attributes:
        type: The error category (e.g., "PlanningError", "ExecutionError")
        message: Human-readable error description
        details: Additional context and metadata about the error
        timestamp: ISO-format timestamp of when the error occurred
        recoverable: Whether the error allows for recovery/retry
    """

    type: str
    message: str
    details: dict[str, Any]
    timestamp: str
    recoverable: bool


def planning_error(message: str, details: dict[str, Any] | None = None) -> AgentError:
    """
    Create a PlanningError for failures in the planning phase.

    When it occurs:
        - Invalid or conflicting goal specifications
        - Inability to decompose goals into actionable subgoals
        - Planning constraints violated

    Which subsystem emits it:
        - Planner

    Expected recovery semantics:
        Recoverable. Retry with refined constraints or adjusted goals.

    Args:
        message: Description of the planning failure
        details: Additional context (constraints, goals, etc.)

    Returns:
        AgentError instance with type="PlanningError"
    """
    return AgentError(
        type="PlanningError",
        message=message,
        details=details or {},
        timestamp=datetime.utcnow().isoformat(),
        recoverable=True,
    )


def mapping_error(message: str, details: dict[str, Any] | None = None) -> AgentError:
    """
    Create a MappingError for failures in the mapping phase.

    When it occurs:
        - Goal cannot be mapped to available skills
        - Skill compatibility issues
        - Parameter binding failures

    Which subsystem emits it:
        - Mapper

    Expected recovery semantics:
        Recoverable. Retry with alternative skills or refined parameters.

    Args:
        message: Description of the mapping failure
        details: Additional context (goals, skills, bindings, etc.)

    Returns:
        AgentError instance with type="MappingError"
    """
    return AgentError(
        type="MappingError",
        message=message,
        details=details or {},
        timestamp=datetime.utcnow().isoformat(),
        recoverable=True,
    )


def execution_error(message: str, details: dict[str, Any] | None = None) -> AgentError:
    """
    Create an ExecutionError for failures during skill execution.

    When it occurs:
        - Skill invocation fails
        - External service unavailable
        - Unexpected runtime exceptions

    Which subsystem emits it:
        - Executor

    Expected recovery semantics:
        Recoverable. Retry execution with backoff or fallback skills.

    Args:
        message: Description of the execution failure
        details: Additional context (skill, exception, state, etc.)

    Returns:
        AgentError instance with type="ExecutionError"
    """
    return AgentError(
        type="ExecutionError",
        message=message,
        details=details or {},
        timestamp=datetime.utcnow().isoformat(),
        recoverable=True,
    )


def state_error(message: str, details: dict[str, Any] | None = None) -> AgentError:
    """
    Create a StateError for failures in state management.

    When it occurs:
        - Inconsistent state transitions
        - Violation of state invariants
        - Corruption or loss of critical state

    Which subsystem emits it:
        - State Manager

    Expected recovery semantics:
        Not recoverable. Indicates fatal inconsistency requiring intervention.

    Args:
        message: Description of the state failure
        details: Additional context (expected state, actual state, etc.)

    Returns:
        AgentError instance with type="StateError"
    """
    return AgentError(
        type="StateError",
        message=message,
        details=details or {},
        timestamp=datetime.utcnow().isoformat(),
        recoverable=False,
    )


def governance_error(message: str, details: dict[str, Any] | None = None) -> AgentError:
    """
    Create a GovernanceError for policy and governance violations.

    When it occurs:
        - Action violates safety policies
        - Unauthorized operations attempted
        - Compliance constraints breached

    Which subsystem emits it:
        - Governance layer

    Expected recovery semantics:
        Not recoverable. Represents a policy violation requiring review.

    Args:
        message: Description of the governance violation
        details: Additional context (policy, action, constraints, etc.)

    Returns:
        AgentError instance with type="GovernanceError"
    """
    return AgentError(
        type="GovernanceError",
        message=message,
        details=details or {},
        timestamp=datetime.utcnow().isoformat(),
        recoverable=False,
    )


def confidence_error(message: str, details: dict[str, Any] | None = None) -> AgentError:
    """
    Create a ConfidenceError for low confidence in decisions or outputs.

    When it occurs:
        - Model confidence below threshold
        - Semantic uncertainty in interpretation
        - Ambiguous or contradictory signals

    Which subsystem emits it:
        - Decision components (planner, mapper, executor)

    Expected recovery semantics:
        Recoverable. Request clarification or retry with adjusted thresholds.

    Args:
        message: Description of the confidence issue
        details: Additional context (confidence scores, thresholds, etc.)

    Returns:
        AgentError instance with type="ConfidenceError"
    """
    return AgentError(
        type="ConfidenceError",
        message=message,
        details=details or {},
        timestamp=datetime.utcnow().isoformat(),
        recoverable=True,
    )


def semantic_error(message: str, details: dict[str, Any] | None = None) -> AgentError:
    """
    Create a SemanticError for misalignment in interpretation or meaning.

    When it occurs:
        - Goal interpretation diverges from intent
        - Output semantics differ from expected
        - Language model misunderstanding

    Which subsystem emits it:
        - Semantic analysis components

    Expected recovery semantics:
        Recoverable. Retry with clarified context or refined prompts.

    Args:
        message: Description of the semantic mismatch
        details: Additional context (interpretation, intent, etc.)

    Returns:
        AgentError instance with type="SemanticError"
    """
    return AgentError(
        type="SemanticError",
        message=message,
        details=details or {},
        timestamp=datetime.utcnow().isoformat(),
        recoverable=True,
    )

"""
Base Agent Error Class - Foundation for all agent runtime errors.

AgentError is a deterministic, strongly-typed error representation used across
the planner, mapper, executor, and state manager.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
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

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp,
            "recoverable": self.recoverable,
        }


class PlanningError(AgentError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            type="PlanningError",
            message=message,
            details=details or {},
            timestamp=datetime.now(timezone.utc).isoformat(),
            recoverable=True,
        )
    """
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


class MappingError(AgentError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            type="MappingError",
            message=message,
            details=details or {},
            timestamp=datetime.now(timezone.utc).isoformat(),
            recoverable=True,
        )
    """
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


class ExecutionError(AgentError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            type="ExecutionError",
            message=message,
            details=details or {},
            timestamp=datetime.now(timezone.utc).isoformat(),
            recoverable=True,
        )
    """
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


class StateError(AgentError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            type="StateError",
            message=message,
            details=details or {},
            timestamp=datetime.now(timezone.utc).isoformat(),
            recoverable=False,
        )
    """
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


class GovernanceError(AgentError, Exception):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            type="GovernanceError",
            message=message,
            details=details or {},
            timestamp=datetime.now(timezone.utc).isoformat(),
            recoverable=False,
        )
    """
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


class ConfidenceError(AgentError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            type="ConfidenceError",
            message=message,
            details=details or {},
            timestamp=datetime.now(timezone.utc).isoformat(),
            recoverable=True,
        )
    """
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


class SemanticError(AgentError):
    """SemanticError: misalignment in interpretation or meaning."""
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            type="SemanticError",
            message=message,
            details=details or {},
            timestamp=datetime.now(timezone.utc).isoformat(),
            recoverable=True,
        )
    """
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

    """

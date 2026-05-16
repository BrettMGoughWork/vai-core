"""
Error Types and Recovery Semantics - Core error taxonomy and recovery mapping for agent runtime.

Exports:
  - AgentError dataclass and factory functions for error creation
  - RecoveryAction enum and mapping function for recovery semantics
"""

from .error_types import (
    AgentError,
    planning_error,
    mapping_error,
    execution_error,
    state_error,
    governance_error,
    confidence_error,
    semantic_error,
)
from .recovery import (
    RecoveryAction,
    map_error_to_recovery,
)

__all__ = [
    "AgentError",
    "planning_error",
    "mapping_error",
    "execution_error",
    "state_error",
    "governance_error",
    "confidence_error",
    "semantic_error",
    "RecoveryAction",
    "map_error_to_recovery",
]

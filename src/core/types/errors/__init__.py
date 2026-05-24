"""
Error Types and Recovery Semantics - Core error taxonomy and recovery mapping for agent runtime.

Exports:
  - AgentError dataclass and factory functions for error creation
  - RecoveryAction enum and mapping function for recovery semantics
"""

from .AgentError import AgentError, SemanticError, GovernanceError, ConfidenceError, StateError, ExecutionError, MappingError, PlanningError
from .LLMError import LLMError
from .SystemError import SystemError
from .ToolError import ToolError
from .recovery import (
    RecoveryAction,
    map_error_to_recovery,
)

__all__ = [
    "AgentError",
    "SystemError",
    "ToolError",
    "ValidationError",
    "LLMError",
    "RecoveryAction",
    "SemanticError",
    "GovernanceError",
    "ConfidenceError",
    "StateError",
    "ExecutionError",
    "MappingError",
    "PlanningError",
    "map_error_to_recovery",
]

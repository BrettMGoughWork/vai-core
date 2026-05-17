"""
Base Agent Error Class - Foundation for all agent runtime errors.

AgentError is a deterministic, strongly-typed error representation used across
the planner, mapper, executor, and state manager.
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

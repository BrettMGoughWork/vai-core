"""Safe failure representation for error handling."""

from dataclasses import dataclass, field
from typing import Any

from src.core.types.errors import AgentError


@dataclass
class SafeFailure:
    """Safely represents a failure with error type, message, and metadata."""

    error_type: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


def make_safe_failure(error: Exception, metadata: dict[str, Any] | None = None) -> SafeFailure:
    """Create a SafeFailure from an exception.
    
    Args:
        error: The exception to convert.
        metadata: Optional additional metadata to include.
    
    Returns:
        A SafeFailure instance with extracted error information.
    """
    return SafeFailure(
        error_type=error.__class__.__name__,
        message=str(error),
        metadata=metadata or {},
    )

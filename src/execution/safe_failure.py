"""Safe failure representation for error handling."""

from dataclasses import dataclass, field
from importlib import metadata
from typing import Any, Optional

@dataclass
class SafeFailure:
    """Safely represents a failure with error type, message, and metadata."""
    error_type: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)

    # Optional runtime-only fields (not included in equality/hash)
    error: Optional[Exception] = None
    summary: Optional[str] = None

    @property
    def is_error(self) -> bool:
        return True

    @property
    def is_tool(self) -> bool:
        # Treat as tool failure
        return self.error_type == "ToolError"
    
    @property
    def text(self) -> str:
        return self.summary or str(self.error)

    @property
    def tool_name(self) -> Optional[str]:
        return getattr(self.error, "tool_name", None)

def make_safe_failure(error: Exception, metadata: None) -> SafeFailure:
    """Create a SafeFailure from an exception.
    
    Args:
        error: The exception to convert.
        metadata: Optional additional metadata to include.
    
    Returns:
        A SafeFailure instance with extracted error information.
    """
    return SafeFailure(
        error_type=type(error).__name__,
        message=str(error),
        metadata=metadata or {},
        error=error,
        summary=str(error),
    )

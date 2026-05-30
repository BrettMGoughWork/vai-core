from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class SafeFailure:
    error_type: str
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_exception(exc: Exception) -> "SafeFailure":
        return SafeFailure(
            error_type=exc.__class__.__name__,
            message=str(exc),
        )

    @property
    def is_error(self) -> bool:
        return True


def make_safe_failure(exc: Exception, metadata: Dict[str, Any] | None = None) -> "SafeFailure":
    """Factory for creating SafeFailure from an exception with optional metadata."""
    return SafeFailure(
        error_type=exc.__class__.__name__,
        message=str(exc),
        metadata=metadata or {},
    )
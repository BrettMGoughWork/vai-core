"""
Validation Error Class - Errors related to data or constraint validation.

ValidationError represents failures in input validation, constraint checking,
or type/schema validation.
"""

from .AgentError import AgentError


from datetime import datetime

class ValidationError(AgentError, Exception):
    def __init__(self, message, details=None, timestamp=None, recoverable=False):
        if details is None:
            details = {}
        if timestamp is None:
            timestamp = datetime.utcnow().isoformat()
        super().__init__(
            type="ValidationError",
            message=message,
            details=details,
            timestamp=timestamp,
            recoverable=recoverable
        )
    def to_dict(self) -> dict:
        return super().to_dict()

    """
    Error raised when validation operations fail.

    Covers failures in input validation, constraint violations, type mismatches,
    and schema validation errors.
    """

    pass

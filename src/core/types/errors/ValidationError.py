"""
Validation Error Class - Errors related to data or constraint validation.

ValidationError represents failures in input validation, constraint checking,
or type/schema validation.
"""

from .AgentError import AgentError


class ValidationError(AgentError):
    """
    Error raised when validation operations fail.

    Covers failures in input validation, constraint violations, type mismatches,
    and schema validation errors.
    """

    pass

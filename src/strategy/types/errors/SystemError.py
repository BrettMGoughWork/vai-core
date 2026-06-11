"""
System Error Class - Errors related to system-level failures.

SystemError represents failures in system resources, configuration,
or runtime environment issues.
"""

from .AgentError import AgentError
from src.strategy.types.validation.deadcode_markers import deadcode_ignore


@deadcode_ignore(reason="Defined as part of closed error taxonomy, used via type field")
class SystemError(AgentError):
    """
    Error raised when system-level operations fail.

    Covers failures in resource allocation, system configuration, runtime
    environment issues, and critical system state problems.
    """

    pass

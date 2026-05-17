"""
System Error Class - Errors related to system-level failures.

SystemError represents failures in system resources, configuration,
or runtime environment issues.
"""

from .AgentError import AgentError


class SystemError(AgentError):
    """
    Error raised when system-level operations fail.

    Covers failures in resource allocation, system configuration, runtime
    environment issues, and critical system state problems.
    """

    pass

"""
Tool Error Class - Errors related to tool/skill execution.

ToolError represents failures in tool invocation, parameter binding,
or tool-specific runtime exceptions.
"""

from .AgentError import AgentError


class ToolError(AgentError):
    """
    Error raised when tool operations fail.

    Covers failures in tool execution, unavailable tools, incompatible parameters,
    and external service errors during skill invocation.
    """

    pass

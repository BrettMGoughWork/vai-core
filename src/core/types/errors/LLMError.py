"""
LLM Error Class - Errors related to language model operations.

LLMError represents failures in language model invocation, response parsing,
or LLM-based decision making.
"""

from .AgentError import AgentError


class LLMError(AgentError):
    """
    Error raised when LLM operations fail.

    Covers failures in model invocation, response generation, token limits,
    API errors, and semantic interpretation issues from language models.
    """

    pass

"""
Phase 2.14.1 — S1 Contract Types (backward-compat re-export)
=============================================================

Types have moved to ``src.runtime.interfaces.contract``.
This module re-exports for backward compatibility.
"""

from src.runtime.interfaces.contract import (  # noqa: F401
    PromptRequest,
    PromptResponse,
    ToolCallRequest,
    ToolCallResult,
    S1Error,
    LLMBackendError,
)

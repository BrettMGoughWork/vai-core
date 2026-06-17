"""
Runtime Stratum — LLM Backend Contract
=======================================

Re-exports from the domain stratum (canonical home) plus runtime-specific aliases.
"""

from src.domain.interfaces.contract import PromptRequest as PromptRequest
from src.domain.interfaces.contract import PromptResponse as PromptResponse
from src.domain.interfaces.contract import ToolCallRequest as ToolCallRequest
from src.domain.interfaces.contract import ToolCallResult as ToolCallResult
from src.domain.interfaces.contract import S1Error as S1Error


# ──────────────────────────────────────────────────────────────────────────────
# Runtime-specific aliases
# ──────────────────────────────────────────────────────────────────────────────

LLMBackendError = S1Error
"""Domain alias — S1Error is the canonical Runtime LLM-backend error type."""

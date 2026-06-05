"""
Phase 2.14.1 — S2/S1 Contract Module
=====================================

Exports for the S1 contract layer:
- types: PromptRequest, PromptResponse, ToolCallRequest, ToolCallResult, S1Error
- validators: pure validation functions
- s2_to_s1_adapter: build_prompt_request
- s1_to_s2_adapter: parse_prompt_response
"""

from src.core.planning.s1_contract.types import (
    PromptRequest,
    PromptResponse,
    ToolCallRequest,
    ToolCallResult,
    S1Error,
)

from src.core.planning.s1_contract.validators import (
    validate_prompt_request,
    validate_prompt_response,
    validate_tool_call_request,
    validate_tool_call_result,
    validate_s1_error,
    validate_prompt_request_detailed,
    validate_prompt_response_detailed,
)

from src.core.planning.s1_contract.s2_to_s1_adapter import build_prompt_request, validate_s2_to_s1, validate_s2_to_s1_detailed
from src.core.planning.s1_contract.s1_to_s2_adapter import parse_prompt_response, validate_s1_to_s2, validate_s1_to_s2_detailed

__all__ = [
    # Types
    "PromptRequest",
    "PromptResponse",
    "ToolCallRequest",
    "ToolCallResult",
    "S1Error",
    # Validators
    "validate_prompt_request",
    "validate_prompt_response",
    "validate_tool_call_request",
    "validate_tool_call_result",
    "validate_s1_error",
    "validate_prompt_request_detailed",
    "validate_prompt_response_detailed",
    # Adapter-level validators
    "validate_s2_to_s1",
    "validate_s2_to_s1_detailed",
    "validate_s1_to_s2",
    "validate_s1_to_s2_detailed",
    # Adapters
    "build_prompt_request",
    "parse_prompt_response",
]

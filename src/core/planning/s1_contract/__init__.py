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
from src.core.planning.s1_contract.s1_client import call_s1_backend
from src.core.planning.s1_contract.s1_simulation_backend import simulate_prompt_response
from src.core.planning.s1_contract.s1_prompt_builder import build_llm_prompt
from src.core.planning.s1_contract.s1_response_validator import validate_llm_response
from src.core.planning.s1_contract.s1_to_s2_adapter import map_s1_error_to_agent_error
from src.core.planning.s1_contract.s1_simulation_fixtures import (
    DEFAULT_DRIFT_OUTPUT,
    DEFAULT_REPAIR_OUTPUT,
    DEFAULT_REFLECTION_OUTPUT,
    DEFAULT_PLAN_SHAPING_OUTPUT,
    STRUCTURAL_DRIFT_TEMPLATE,
    BEHAVIOURAL_DRIFT_TEMPLATE,
    REPAIR_FILL_MISSING_TEMPLATE,
    make_default_output,
    make_minimal_plan_context,
)
from src.core.planning.s1_contract.readiness import (
    ReadinessResult,
    check_llm_on_readiness,
    render_readiness_status,
)

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
    "map_s1_error_to_agent_error",
    # S1 backend (2.14.3)
    "call_s1_backend",
    "simulate_prompt_response",
    # Prompt builder & response validator (2.14.4)
    "build_llm_prompt",
    "validate_llm_response",
    # Fixtures (2.14.3)
    "DEFAULT_DRIFT_OUTPUT",
    "DEFAULT_REPAIR_OUTPUT",
    "DEFAULT_REFLECTION_OUTPUT",
    "DEFAULT_PLAN_SHAPING_OUTPUT",
    "STRUCTURAL_DRIFT_TEMPLATE",
    "BEHAVIOURAL_DRIFT_TEMPLATE",
    "REPAIR_FILL_MISSING_TEMPLATE",
    "make_default_output",
    "make_minimal_plan_context",
    # Readiness (2.14.6)
    "ReadinessResult",
    "check_llm_on_readiness",
    "render_readiness_status",
]

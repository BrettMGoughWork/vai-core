"""
Runtime Stratum — Integration Interfaces
=========================================

Canonical re-exports of the Runtime stratum's contracts.

The Runtime stratum owns:
- The LLM backend contract (PromptRequest, PromptResponse, …)
- Safe-failure semantics
- Retry / circuit-breaker primitives
- Execution-scoped error types

These types physically reside in various modules (some in
``src/strategy/planning/s1_contract`` for historical reasons); this
package re-exports them under the Runtime domain name so that
consuming strata always import from ``src.runtime.interfaces``.
"""

from __future__ import annotations

# ── LLM Backend Contract (S1 contract, owned by Runtime) ──────────────────

from src.runtime.interfaces.contract import (
    PromptRequest as PromptRequest,
    PromptResponse as PromptResponse,
    ToolCallRequest as ToolCallRequest,
    ToolCallResult as ToolCallResult,
    S1Error as S1Error,
    LLMBackendError as LLMBackendError,
)

from src.strategy.planning.s1_contract.s1_client import (
    call_s1_backend as call_s1_backend,
    call_runtime_backend as call_runtime_backend,
)

from src.strategy.planning.s1_contract.s1_real_client import (
    call_llm as call_llm,
    ENABLE_REAL_LLM as ENABLE_REAL_LLM,
    S1RealLLMError as S1RealLLMError,
)

from src.strategy.planning.s1_contract.s1_simulation_backend import (
    simulate_prompt_response as simulate_prompt_response,
)

from src.strategy.planning.s1_contract.s1_prompt_builder import (
    build_llm_prompt as build_llm_prompt,
)

from src.strategy.planning.s1_contract.s1_response_validator import (
    validate_llm_response as validate_llm_response,
)

from src.strategy.planning.s1_contract.s1_to_s2_adapter import (
    parse_prompt_response as parse_prompt_response,
    map_s1_error_to_agent_error as map_s1_error_to_agent_error,
)

from src.strategy.planning.s1_contract.s2_to_s1_adapter import (
    build_prompt_request as build_s2_prompt_request,
    validate_s2_to_s1 as validate_s2_to_s1,
)

from src.strategy.planning.s1_contract.validators import (
    validate_prompt_request as validate_prompt_request,
    validate_prompt_response as validate_prompt_response,
    validate_tool_call_request as validate_tool_call_request,
    validate_tool_call_result as validate_tool_call_result,
    validate_s1_error as validate_s1_error,
)

from src.strategy.planning.s1_contract.s1_simulation_fixtures import (
    DEFAULT_DRIFT_OUTPUT as DEFAULT_DRIFT_OUTPUT,
    DEFAULT_REPAIR_OUTPUT as DEFAULT_REPAIR_OUTPUT,
    DEFAULT_REFLECTION_OUTPUT as DEFAULT_REFLECTION_OUTPUT,
    DEFAULT_PLAN_SHAPING_OUTPUT as DEFAULT_PLAN_SHAPING_OUTPUT,
    STRUCTURAL_DRIFT_TEMPLATE as STRUCTURAL_DRIFT_TEMPLATE,
    BEHAVIOURAL_DRIFT_TEMPLATE as BEHAVIOURAL_DRIFT_TEMPLATE,
    REPAIR_FILL_MISSING_TEMPLATE as REPAIR_FILL_MISSING_TEMPLATE,
    make_default_output as make_default_output,
    make_minimal_plan_context as make_minimal_plan_context,
)

from src.strategy.planning.s1_contract.readiness import (
    ReadinessResult as ReadinessResult,
    check_llm_on_readiness as check_llm_on_readiness,
    render_readiness_status as render_readiness_status,
)

# ── Safe Failure ──────────────────────────────────────────────────────────

from src.runtime.safe_failure import (
    SafeFailure as SafeFailure,
    make_safe_failure as make_safe_failure,
)

# ── Error Types ───────────────────────────────────────────────────────────

from src.runtime.errors import (
    ToolExecutionError as ToolExecutionError,
)

# ── Retry / Circuit Breaker ───────────────────────────────────────────────

from src.runtime.retry.retry_policy import (
    RetryPolicy as RetryPolicy,
    RetryStrategy as RetryStrategy,
)

from src.runtime.retry.llm_retry_wrapper import (
    call_with_retry as call_with_retry,
)

from src.runtime.retry.tool_retry_wrapper import (
    execute_with_retry as execute_with_retry,
)

from src.runtime.retry.circuit_breaker import (
    CircuitBreaker as CircuitBreaker,
)

# ── Panic Guard ───────────────────────────────────────────────────────────

from src.runtime.panic_guard import (
    with_panic_guard as with_panic_guard,
)

# ── Self-healing / Degraded Mode ──────────────────────────────────────────

from src.runtime.self_healing import (
    SelfHealingController as SelfHealingController,
)

from src.runtime.degraded_mode import (
    DegradedModeController as DegradedModeController,
)

from src.runtime.poison_job_detector import (
    PoisonJobDetector as PoisonJobDetector,
)

__all__ = [
    # LLM Backend
    "PromptRequest",
    "PromptResponse",
    "ToolCallRequest",
    "ToolCallResult",
    "S1Error",
    "LLMBackendError",
    "call_s1_backend",
    "call_runtime_backend",
    "call_llm",
    "ENABLE_REAL_LLM",
    "S1RealLLMError",
    "simulate_prompt_response",
    "build_llm_prompt",
    "validate_llm_response",
    "parse_prompt_response",
    "map_s1_error_to_agent_error",
    "build_s2_prompt_request",
    "validate_s2_to_s1",
    "validate_prompt_request",
    "validate_prompt_response",
    "validate_tool_call_request",
    "validate_tool_call_result",
    "validate_s1_error",
    # Fixtures
    "DEFAULT_DRIFT_OUTPUT",
    "DEFAULT_REPAIR_OUTPUT",
    "DEFAULT_REFLECTION_OUTPUT",
    "DEFAULT_PLAN_SHAPING_OUTPUT",
    "STRUCTURAL_DRIFT_TEMPLATE",
    "BEHAVIOURAL_DRIFT_TEMPLATE",
    "REPAIR_FILL_MISSING_TEMPLATE",
    "make_default_output",
    "make_minimal_plan_context",
    # Readiness
    "ReadinessResult",
    "check_llm_on_readiness",
    "render_readiness_status",
    # Safe failure
    "SafeFailure",
    "make_safe_failure",
    # Errors
    "ToolExecutionError",
    # Retry
    "RetryPolicy",
    "RetryStrategy",
    "call_with_retry",
    "execute_with_retry",
    "CircuitBreaker",
    # Panic guard
    "with_panic_guard",
    # Self-healing
    "SelfHealingController",
    "DegradedModeController",
    "PoisonJobDetector",
]

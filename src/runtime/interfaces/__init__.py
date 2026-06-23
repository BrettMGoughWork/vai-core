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

from src.domain.interfaces.contract import (
    PromptRequest as PromptRequest,
    PromptResponse as PromptResponse,
    ToolCallRequest as ToolCallRequest,
    ToolCallResult as ToolCallResult,
    S1Error as S1Error,
)

LLMBackendError = S1Error
"""Runtime alias — S1Error is the canonical LLM-backend error type."""


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
    # LLM Backend Contract
    "PromptRequest",
    "PromptResponse",
    "ToolCallRequest",
    "ToolCallResult",
    "S1Error",
    "LLMBackendError",
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

"""
Phase 2.14.3 — S1 Client Router
================================

Pure routing function that dispatches PromptRequests to the
appropriate S1 backend (simulation or real_llm).

The real_llm backend is stubbed — it returns a minimal valid
PromptResponse without calling any actual LLM. That integration
is scheduled for Phase 2.14.7.

Pure function. No I/O. No inference.
"""

from __future__ import annotations

from src.core.planning.s1_contract.types import PromptRequest, PromptResponse
from src.core.planning.s1_contract.s1_simulation_backend import simulate_prompt_response
from src.core.planning.s1_contract.s1_simulation_fixtures import (
    DEFAULT_DRIFT_OUTPUT,
    DEFAULT_REPAIR_OUTPUT,
    DEFAULT_REFLECTION_OUTPUT,
    DEFAULT_PLAN_SHAPING_OUTPUT,
)


_ALLOWED_BACKENDS = {"simulation", "real_llm"}


def call_s1_backend(request: PromptRequest, backend: str = "simulation") -> PromptResponse:
    """Route a PromptRequest to the specified S1 backend.

    Args:
        request: A validated PromptRequest from S2.
        backend: One of "simulation" (default) or "real_llm" (stubbed).

    Returns:
        A PromptResponse object.

    Raises:
        ValueError: If backend is not recognised.
    """
    if backend not in _ALLOWED_BACKENDS:
        raise ValueError(
            f"Unknown backend: {backend!r}. Allowed: {sorted(_ALLOWED_BACKENDS)}"
        )

    if backend == "simulation":
        return simulate_prompt_response(request)

    # real_llm stub — returns a generic "ok" response
    # Real LLM integration happens in Phase 2.14.7
    return PromptResponse(
        output={
            "drift_detected": False,
            "drift_type": None,
            "drift_severity": "minor",
            "drift_detail": [],
            "repairs": [],
            "quality": {"below_threshold": False},
            "structural_deviation": {},
            **DEFAULT_REFLECTION_OUTPUT,
            **DEFAULT_PLAN_SHAPING_OUTPUT,
        },
        tool_calls=[],
        errors=[],
    )

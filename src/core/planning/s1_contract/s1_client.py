"""
Phase 2.14.4 — S1 Client Router
================================

Pure routing function that dispatches PromptRequests to the
appropriate S1 backend (simulation or real_llm) and validates
raw LLM output before returning to S2.

The real_llm backend is stubbed — it produces a deterministic
JSON string that is then validated through the full response
validation pipeline. Real LLM integration is scheduled for
Phase 2.14.7.

Pure function. No I/O. No inference.
"""

from __future__ import annotations

import json
from typing import Union

from src.core.planning.s1_contract.types import PromptRequest, PromptResponse, S1Error
from src.core.planning.s1_contract.s1_simulation_backend import simulate_prompt_response
from src.core.planning.s1_contract.s1_response_validator import validate_llm_response
from src.core.planning.s1_contract.s1_simulation_fixtures import (
    DEFAULT_DRIFT_OUTPUT,
    DEFAULT_REPAIR_OUTPUT,
    DEFAULT_REFLECTION_OUTPUT,
    DEFAULT_PLAN_SHAPING_OUTPUT,
)


_ALLOWED_BACKENDS = {"simulation", "real_llm"}


def _generate_real_llm_raw_response(request: PromptRequest) -> str:
    """Generate a deterministic JSON string simulating raw LLM output.

    Pure function. No I/O. No inference.
    Used to exercise the full response validation pipeline.
    """
    response_dict = {
        "drift_detected": False,
        "drift_type": None,
        "drift_severity": "minor",
        "drift_detail": [],
        "repairs": [],
        "quality": {"below_threshold": False},
        "structural_deviation": {},
        **DEFAULT_REFLECTION_OUTPUT,
        **DEFAULT_PLAN_SHAPING_OUTPUT,
    }
    return json.dumps(response_dict)


def call_s1_backend(
    request: PromptRequest, backend: str = "simulation"
) -> Union[PromptResponse, S1Error]:
    """Route a PromptRequest to the specified S1 backend.

    Args:
        request: A validated PromptRequest from S2.
        backend: One of "simulation" (default) or "real_llm" (stubbed).

    Returns:
        A PromptResponse on success, or an S1Error if validation fails.

    Raises:
        ValueError: If backend is not recognised.
    """
    if backend not in _ALLOWED_BACKENDS:
        raise ValueError(
            f"Unknown backend: {backend!r}. Allowed: {sorted(_ALLOWED_BACKENDS)}"
        )

    if backend == "simulation":
        return simulate_prompt_response(request)

    # real_llm stub — generate raw JSON, then validate through full pipeline
    # Real LLM integration happens in Phase 2.14.7
    raw_text = _generate_real_llm_raw_response(request)
    return validate_llm_response(raw_text)

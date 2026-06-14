"""
Phase 2.14.7 — S1 Client Router
================================

Pure routing function that dispatches PromptRequests to the
appropriate S1 backend (simulation or real_llm).

- ``backend="simulation"`` → deterministic mock (Phase 2.14.3)
- ``backend="real_llm"``  → real LLM provider behind kill‑switch (Phase 2.14.7)

All raw LLM output is validated through ``validate_llm_response``
before being returned to S2.  S2 never sees raw text or malformed
responses.

Pure function for routing logic.  I/O only occurs inside the real
LLM client path.
"""

from __future__ import annotations

import json
from typing import Optional, Union

from src.strategy.planning.s1_contract.types import PromptRequest, PromptResponse, S1Error
from src.strategy.planning.s1_contract.s1_simulation_backend import simulate_prompt_response
from src.strategy.planning.s1_contract.s1_response_validator import validate_llm_response
from src.strategy.planning.s1_contract.s1_simulation_fixtures import (
    DEFAULT_DRIFT_OUTPUT,
    DEFAULT_REPAIR_OUTPUT,
    DEFAULT_REFLECTION_OUTPUT,
    DEFAULT_PLAN_SHAPING_OUTPUT,
)


_ALLOWED_BACKENDS = {"simulation", "real_llm"}


def _generate_real_llm_raw_response(request: PromptRequest) -> str:
    """Generate a deterministic JSON string simulating raw LLM output.

    Pure function. No I/O. No inference.
    Used as a fallback when the real LLM is disabled or as a stub
    in tests that don't want to hit a live provider.
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


def _resolve_model(llm_raw: dict) -> str:
    """Resolve the active model from variant config.

    If model_variants and active_variant are set, use the variant mapping.
    Otherwise fall back to the top-level model field.
    Pure function.
    """
    variants = llm_raw.get("model_variants", {})
    active = llm_raw.get("active_variant", "")
    if variants and active in variants:
        return variants[active]
    return llm_raw.get("model", "default")


def _get_llm_transport():
    """Lazily create an LLMTransport for the configured provider.

    Returns None if no provider is configured or the config is missing.
    Uses the canonical LLM builder factory.
    """
    try:
        from src.strategy.llm.builder import create_llm_transport
    except ImportError:
        return None

    try:
        import yaml
        from pathlib import Path

        config_path = Path("config/config.yaml")
        if not config_path.exists():
            return None

        with open(config_path, "r") as f:
            raw = yaml.safe_load(f)

        llm_raw = raw.get("llm", {})
        provider_name = llm_raw.get("provider", "")
        if not provider_name:
            return None

        model = _resolve_model(llm_raw)

        from src.strategy.state.config import LLMConfig
        llm_config = LLMConfig(
            provider=llm_raw.get("provider", ""),
            model=model,
            temperature=llm_raw.get("temperature", 0.0),
            max_tokens=llm_raw.get("max_tokens", 4096),
        )
    except Exception:
        return None

    return create_llm_transport(llm_config)


def call_s1_backend(
    request: PromptRequest, backend: str = "simulation"
) -> Union[PromptResponse, S1Error]:
    """Route a PromptRequest to the specified S1 backend.

    Args:
        request: A validated PromptRequest from S2.
        backend: One of ``"simulation"`` (default, deterministic) or
                 ``"real_llm"`` (live LLM behind kill‑switch).

    Returns:
        A PromptResponse on success, or an S1Error if:
          - The kill‑switch is active (``ENABLE_REAL_LLM=False``)
          - The LLM returns invalid/malformed output
          - The provider call fails irrecoverably

    Raises:
        ValueError: If backend is not recognised.
    """
    if backend not in _ALLOWED_BACKENDS:
        raise ValueError(
            f"Unknown backend: {backend!r}. Allowed: {sorted(_ALLOWED_BACKENDS)}"
        )

    if backend == "simulation":
        return simulate_prompt_response(request)

    # ── real_llm path ────────────────────────────────────────────────────

    # 1. Kill‑switch — check before any network call
    from src.strategy.planning.s1_contract.s1_real_client import ENABLE_REAL_LLM

    if not ENABLE_REAL_LLM:
        return S1Error(
            type="real_llm_disabled",
            message="Kill-switch active — real LLM backend is not enabled.",
            details={
                "hint": "Set ENABLE_REAL_LLM=True in s1_real_client.py only after "
                        "passing the readiness checklist (Phase 2.14.6)."
            },
        )

    # 2. Call the real LLM (may raise S1RealLLMError)
    try:
        from src.strategy.planning.s1_contract.s1_real_client import call_llm
        raw_text = call_llm(request)
    except Exception as exc:
        return S1Error(
            type="s1_provider_failure",
            message=f"Real LLM call failed: {str(exc)}",
            details={"exception_type": type(exc).__name__},
        )

    # 3. Validate → PromptResponse | S1Error
    return validate_llm_response(raw_text)


# Domain-name alias — call_runtime_backend is the canonical name.
call_runtime_backend = call_s1_backend

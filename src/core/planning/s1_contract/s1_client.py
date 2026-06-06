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


def _get_llm_transport():
    """Lazily create an LLMTransport for the configured provider.

    Returns None if no provider is configured or the config is missing.
    """
    try:
        from src.core.llm.transport import LLMTransport
        from src.core.config.loader import AppConfigLoader
    except ImportError:
        return None

    loader = AppConfigLoader.load()
    if loader is None:
        return None

    provider_name = loader.config.get("llm", {}).get("provider")
    if not provider_name:
        return None

    model = loader.config.get("llm", {}).get("model", "default")
    temperature = loader.config.get("llm", {}).get("temperature", 0.0)
    max_tokens = loader.config.get("llm", {}).get("max_tokens", 4096)

    client = _make_provider_client(provider_name, loader.config)
    if client is None:
        return None

    return LLMTransport(client, model, temperature, max_tokens)


def _make_provider_client(provider_name: str, config: dict):
    """Instantiate the appropriate ChatProvider for the given name."""
    try:
        from src.core.llm.providers.openai import OpenAIChatProvider
        from src.core.llm.providers.anthropic import AnthropicChatProvider
        from src.core.llm.providers.gemini import GeminiChatProvider
        from src.core.llm.providers.deepseek import DeepSeekChatProvider
        from src.core.llm.providers.qwen import QwenChatProvider
        from src.core.llm.providers.mistral import MistralChatProvider
    except ImportError:
        return None

    providers = {
        "openai": OpenAIChatProvider,
        "anthropic": AnthropicChatProvider,
        "gemini": GeminiChatProvider,
        "deepseek": DeepSeekChatProvider,
        "qwen": QwenChatProvider,
        "mistral": MistralChatProvider,
    }

    provider_cls = providers.get(provider_name.lower())
    if provider_cls is None:
        return None

    return provider_cls.from_config(config)


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
    from src.core.planning.s1_contract.s1_real_client import ENABLE_REAL_LLM

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
        from src.core.planning.s1_contract.s1_real_client import call_llm
        raw_text = call_llm(request)
    except Exception as exc:
        return S1Error(
            type="s1_provider_failure",
            message=f"Real LLM call failed: {str(exc)}",
            details={"exception_type": type(exc).__name__},
        )

    # 3. Validate → PromptResponse | S1Error
    return validate_llm_response(raw_text)

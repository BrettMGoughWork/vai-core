"""
Phase 2.14.7 — S1 Client Router
================================

Pure routing function that dispatches PromptRequests to the
appropriate S1 backend (simulation or real_llm).

- ``backend="simulation"`` → deterministic planner mock (Phase 2.14.3)
- ``backend="mock"``      → conversational stub for the S5 CLI demo
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


_ALLOWED_BACKENDS = {"simulation", "mock", "conversational", "real_llm"}


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


def _mock_response(message: str, agent_id: str) -> str:
    """Produce a simple conversational mock response for the CLI demo.

    This is **not** a real LLM response — it's a deterministic stub
    that exercises the full S5 pipeline (supervisor, cognitive loop,
    state persistence) with human-readable output.
    """
    haikus = [
        "Silent code compiles,\nA single bug lies waiting,\nThe evening grows long.",
        "Lights blink on the board,\nData streams across the wire,\nAll systems are go.",
        "An error message,\nDeep in the terminal logs,\nSpring rain on the roof.",
    ]
    import random
    haiku = random.choice(haikus)
    return (
        f"[{agent_id} v1.0] Here's your haiku:\n\n"
        f"{haiku}\n\n"
        f"---\n"
        f"_This is a mock response from the S5 agent pipeline. "
        f"The cognitive loop, supervisor, and state store are all wired correctly._"
    )


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


# ── DI slot: LLM transport (set by the composition root) ──────────
# S2 does NOT import S1 types to create a transport itself.
# The S5 composition root injects the transport via set_llm_transport().

_llm_transport: object | None = None
"""Module-level DI slot for the S1 LLM transport.

Set by the composition root during startup.
S2 never imports S1 internals to create a transport.
"""


def set_llm_transport(transport: object | None) -> None:
    """Inject an S1 LLM transport from the composition root (S5)."""
    global _llm_transport
    _llm_transport = transport


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

    if backend == "mock":
        message = request.prompt.get("message", "(no message)")
        agent_id = request.prompt.get("agent_id", "unknown")
        return PromptResponse(
            output={
                "is_complete": True,
                "message": _mock_response(message, agent_id),
                "confidence": 0.95,
            },
        )

    # ── conversational path ───────────────────────────────────────────────
    # Sends the user message directly to a real LLM and wraps the response
    # into the format the S5 supervisor expects.
    if backend == "conversational":
        if _llm_transport is None:
            return S1Error(
                type="llm_transport_unavailable",
                message="No LLM transport configured. The composition root must inject one via set_llm_transport().",
                details={"hint": "Call set_llm_transport(transport) in the composition root before use."},
            )

        transport = _llm_transport

        user_message = request.prompt.get("message", "")
        agent_id = request.prompt.get("agent_id", "assistant")
        agent_name = (
            request.prompt.get("agent_metadata", {})
            .get("name", agent_id)
        )
        description = request.prompt.get("agent_metadata", {}).get("description", "")

        system_prompt = (
            f"You are {agent_name}, an AI assistant in the VAI platform.\n"
            f"{description}\n\n"
            "Respond conversationally. Be concise, helpful, and accurate."
        )

        try:
            raw_text = transport.complete(
                f"{system_prompt}\n\nUser: {user_message}\n{agent_name}:"
            )
            import time
            return PromptResponse(
                output={
                    "is_complete": True,
                    "message": raw_text.strip(),
                    "confidence": 0.95,
                },
            )
        except Exception as exc:
            return S1Error(
                type="conversational_llm_failure",
                message=f"Conversational LLM call failed: {str(exc)}",
                details={"exception_type": type(exc).__name__},
            )

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

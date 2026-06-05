"""
Phase 2.8.2 — Semantic Drift Signals
====================================

Converts ``SemanticMismatch`` objects from 2.8.1 into structured
``SemanticDriftSignal`` objects.

Signal mapping (deterministic)
------------------------------
Each mismatch type maps to exactly one drift signal type:

- ``step_mismatch`` → ``contradictprior_behaviour``
- ``plan_mismatch`` → ``contradictplan``
- ``subgoal_mismatch`` → ``contradictsubgoal``
- ``memory_mismatch`` → ``contradictmemory``

Confidence and details are copied defensively from the mismatch.
Signals are emitted in a deterministic order based on signal type:
``contradictplan``, ``contradictsubgoal``, ``contradictmemory``,
``contradictprior_behaviour``.

The emitter is **pure**, **deterministic**, and never mutates inputs.
"""
from __future__ import annotations

from typing import Dict, List

from src.core.planning.drift.semantic_signal_types import (
    SemanticDriftSignal,
    SemanticMismatch,
)


# ── mismatch → signal type mapping ──────────────────────────────────────────

_MISMATCH_TO_SIGNAL_TYPE: Dict[str, str] = {
    "step_mismatch": "contradictprior_behaviour",
    "plan_mismatch": "contradictplan",
    "subgoal_mismatch": "contradictsubgoal",
    "memory_mismatch": "contradictmemory",
}

# Deterministic emission order
_SIGNAL_EMISSION_ORDER = (
    "contradictplan",
    "contradictsubgoal",
    "contradictmemory",
    "contradictprior_behaviour",
)
_SIGNAL_ORDER_INDEX = {sig: i for i, sig in enumerate(_SIGNAL_EMISSION_ORDER)}


# ── public API ──────────────────────────────────────────────────────────────


def emit_semantic_drift_signals(
    mismatches: List[SemanticMismatch],
) -> List[SemanticDriftSignal]:
    """
    Convert semantic mismatches into deterministic drift signals.

    Args:
        mismatches:
            A list of ``SemanticMismatch`` objects from
            :func:`~semantic_validator.validate_semantics`.

    Returns:
        A deterministic, ordered list of ``SemanticDriftSignal`` objects.
        Order: ``contradictplan``, ``contradictsubgoal``,
        ``contradictmemory``, ``contradictprior_behaviour``.

        Empty list when ``mismatches`` is empty.

    None of the inputs are mutated.
    """
    if not mismatches:
        return []

    signals: List[SemanticDriftSignal] = []
    for mismatch in mismatches:
        signal_type = _MISMATCH_TO_SIGNAL_TYPE[mismatch.type]
        signals.append(SemanticDriftSignal(
            type=signal_type,  # type: ignore[arg-type]
            confidence=mismatch.confidence,
            details=mismatch.details,
        ))

    # Deterministic sort by emission order
    signals.sort(key=lambda s: _SIGNAL_ORDER_INDEX[s.type])
    return signals

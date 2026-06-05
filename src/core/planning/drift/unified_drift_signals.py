"""
Phase 2.9.1 — Unified Drift Signal Builder
==========================================

Implements ``unify_drift_signals()``, a pure, deterministic function that
merges structural, behavioural, temporal, and semantic drift signals into
a single list of ``UnifiedDriftSignal`` instances with weighting and decay.

Invariants
----------
- Pure — no side effects, no mutation of inputs.
- Deterministic — identical inputs always produce identical outputs.
- JSON‑safe — all outputs are serialisable to JSON.
- No LLM calls, no imports outside stdlib.
"""
from __future__ import annotations

from typing import List, Optional

from src.core.planning.drift.behavioural_signal_types import BehaviouralSignal
from src.core.planning.drift.drift_types import DriftSignal
from src.core.planning.drift.semantic_signal_types import SemanticDriftSignal
from src.core.planning.drift.temporal_signal_types import TemporalDriftSignal
from src.core.planning.drift.unified_drift_types import UnifiedDriftSignal

# ── Source weights (mirror unified_drift_types constants) ─────────────────────

_SOURCE_WEIGHT: dict[str, float] = {
    "structural": 1.0,
    "behavioural": 0.9,
    "temporal": 0.8,
    "semantic": 0.7,
}

_DECAY_STEP: float = 0.1


def _build_previous_index(
    previous: Optional[List[UnifiedDriftSignal]],
) -> dict[tuple[str, str], float]:
    """
    Build a lookup of (source, type) → previous decay value.
    """
    if not previous:
        return {}
    return {(s.source, s.type): s.decay for s in previous}


def _signal_sort_key(signal: UnifiedDriftSignal) -> tuple[str, str]:
    """Deterministic sort key: source first, then type."""
    return (signal.source, signal.type)


def _convert_structural(s: DriftSignal) -> UnifiedDriftSignal:
    """Convert a structural ``DriftSignal`` into a ``UnifiedDriftSignal``."""
    weight = s.metadata.get("confidence", 1.0) * _SOURCE_WEIGHT["structural"]
    weight = min(max(weight, 0.0), 1.0)
    return UnifiedDriftSignal(
        source="structural",
        type=s.type,
        weight=weight,
        decay=1.0,  # placeholder — decay applied after
        confidence=s.metadata.get("confidence", 1.0),
        details=s.metadata,
    )


def _convert_behavioural(s: BehaviouralSignal) -> UnifiedDriftSignal:
    """Convert a behavioural ``BehaviouralSignal`` into a ``UnifiedDriftSignal``."""
    weight = 1.0 * _SOURCE_WEIGHT["behavioural"]  # behavioural has no confidence field
    return UnifiedDriftSignal(
        source="behavioural",
        type=s.signal_type.value,
        weight=weight,
        decay=1.0,
        confidence=1.0,
        details=s.details,
    )


def _convert_temporal(s: TemporalDriftSignal) -> UnifiedDriftSignal:
    """Convert a temporal ``TemporalDriftSignal`` into a ``UnifiedDriftSignal``."""
    weight = s.confidence * _SOURCE_WEIGHT["temporal"]
    weight = min(max(weight, 0.0), 1.0)
    return UnifiedDriftSignal(
        source="temporal",
        type=s.type,
        weight=weight,
        decay=1.0,
        confidence=s.confidence,
        details=s.details,
    )


def _convert_semantic(s: SemanticDriftSignal) -> UnifiedDriftSignal:
    """Convert a semantic ``SemanticDriftSignal`` into a ``UnifiedDriftSignal``."""
    weight = s.confidence * _SOURCE_WEIGHT["semantic"]
    weight = min(max(weight, 0.0), 1.0)
    return UnifiedDriftSignal(
        source="semantic",
        type=s.type,
        weight=weight,
        decay=1.0,
        confidence=s.confidence,
        details=s.details,
    )


# ── Public API ────────────────────────────────────────────────────────────────


def unify_drift_signals(
    structural: List[DriftSignal],
    behavioural: List[BehaviouralSignal],
    temporal: List[TemporalDriftSignal],
    semantic: List[SemanticDriftSignal],
    previous_unified: Optional[List[UnifiedDriftSignal]] = None,
) -> List[UnifiedDriftSignal]:
    """
    Merge all four drift‑signal families into a weighted, decaying unified list.

    Parameters
    ----------
    structural:
        Structural ``DriftSignal`` instances.
    behavioural:
        Behavioural ``BehaviouralSignal`` instances.
    temporal:
        Temporal ``TemporalDriftSignal`` instances.
    semantic:
        Semantic ``SemanticDriftSignal`` instances.
    previous_unified:
        The unified signal list from the previous cycle, used to compute
        decay.  ``None`` on the first cycle.

    Returns
    -------
    list[UnifiedDriftSignal]
        Deterministically sorted list of unified signals with weighting and
        decay applied.  Empty if no input signals are provided.
    """
    previous_index = _build_previous_index(previous_unified)

    converted: list[UnifiedDriftSignal] = []
    converted.extend(_convert_structural(s) for s in structural)
    converted.extend(_convert_behavioural(s) for s in behavioural)
    converted.extend(_convert_temporal(s) for s in temporal)
    converted.extend(_convert_semantic(s) for s in semantic)

    # Apply decay
    result: list[UnifiedDriftSignal] = []
    for signal in converted:
        key = (signal.source, signal.type)
        if key in previous_index:
            new_decay = max(0.0, previous_index[key] - _DECAY_STEP)
        else:
            new_decay = 1.0
        result.append(
            UnifiedDriftSignal(
                source=signal.source,
                type=signal.type,
                weight=signal.weight,
                decay=new_decay,
                confidence=signal.confidence,
                details=signal.details,
            )
        )

    # Deterministic sort: source (alphabetical), then type (alphabetical)
    result.sort(key=_signal_sort_key)
    return result

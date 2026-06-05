"""
Phase 2.6.6 — Behavioural Trace Types
====================================

``BehaviouralTrace`` is a frozen, JSON‑safe dataclass that persists per‑segment
behavioural information across cycles.

It is constructed **after** classification and repair in Phase 2.6.4 / 2.6.5.

Phase 2.7.5 — Temporal Trace Types
==================================

``TemporalTrace`` is a frozen, JSON‑safe dataclass that persists per‑segment
temporal‑reasoning information across cycles.

It is constructed **after** progress detection (2.7.1), temporal drift
signals (2.7.2), classification (2.7.3), and repair (2.7.4).

Phase 2.8.5 — Semantic Trace Types
==================================

``SemanticTrace`` is a frozen, JSON‑safe dataclass that persists per‑segment
semantic‑reasoning information across cycles.

It is constructed **after** semantic validation (2.8.1), semantic drift
signals (2.8.2), classification (2.8.3), and repair (2.8.4).

Fields
------
BehaviouralTrace
    behavioural_deltas
        A JSON‑safe dict describing what changed between the previous segment
        output and the current one.  Contains three sub‑deltas:

        - ``output_delta`` – structural diff of ``last_output``
        - ``metadata_delta`` – structural diff of ``metadata``
        - ``side_effects_delta`` – extracted from signals (if any)

    behavioural_drift_signals
        A defensive copy of the ``BehaviouralSignal`` list from the classification.

    behavioural_repair_actions
        A defensive copy of the repair action strings from 2.6.5.

TemporalTrace
    progress_deltas
        JSON‑safe dict with ``output_delta``, ``metadata_delta``, and
        ``side_effects_delta`` keys describing structural differences
        between previous and current segment outputs.

    stall_reasons
        JSON‑safe list of human‑readable strings explaining why progress
        stalled, derived from ``ProgressSignal`` and ``TemporalDriftSignal``
        of type ``no_progress``.

    oscillation_markers
        JSON‑safe list of oscillation pattern descriptions, derived from
        ``TemporalDriftSignal`` of type ``oscillation``.

SemanticTrace
    semantic_mismatches
        JSON‑safe list of mismatch summary dicts.  Each dict contains
        ``type``, ``confidence``, and ``details`` derived from a
        ``SemanticMismatch`` object.  Sorted deterministically by type.

    semantic_repair_actions
        JSON‑safe list of semantic repair action strings (e.g.
        ``"rewrite plan"``) derived from ``SemanticRepairPlan.repair_actions``.
        Sorted deterministically.

    semantic_drift_history
        JSON‑safe list of classification summary dicts.  Each dict contains
        ``status``, ``categories``, ``confidence``, and ``streak`` derived
        from a ``SemanticDriftClassification``.  The current classification
        is appended to the previous trace's history.

Phase 2.9.5 — Drift Trace Types
===============================

``DriftTrace`` is a frozen, JSON‑safe dataclass that persists per‑segment
unified‑drift information across cycles.

It is constructed **after** unified drift signals (2.9.1), classification
(2.9.2), confirmation (2.9.3), and recovery (2.9.4).

Fields
------
DriftTrace
    unified_drift_history
        JSON‑safe list of ``UnifiedDriftClassification`` summary dicts.
        Each dict contains ``status``, ``severity``, ``categories``,
        ``confidence``, and ``streak``.  The current classification is
        appended to the previous trace's history.

    drift_confidence_evolution
        JSON‑safe list of accumulated confidence values (floats) from
        ``DriftConfirmationState.confidence`` across cycles.

    drift_recovery_decisions
        JSON‑safe list of ``DriftRecoveryDecision`` summary dicts.
        Each dict contains ``action``, ``severity``, ``confidence``,
        ``streak``, and ``hysteresis``.  The current recovery decision
        is appended to the previous trace's history.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, List

from src.core.planning.drift.behavioural_signal_types import BehaviouralSignal
from src.core.types.json_pure import ensure_json_pure


@dataclass(frozen=True)
class BehaviouralTrace:
    """
    Per‑segment behavioural trace persisted across cycles.

    All fields are JSON‑safe.  Defensive copies prevent external mutation.
    """

    behavioural_deltas: Dict[str, Any]
    behavioural_drift_signals: List[BehaviouralSignal]
    behavioural_repair_actions: List[str]

    def __post_init__(self) -> None:
        ensure_json_pure(self.behavioural_deltas)
        object.__setattr__(
            self, "behavioural_deltas", copy.deepcopy(self.behavioural_deltas)
        )
        object.__setattr__(
            self, "behavioural_drift_signals",
            list(self.behavioural_drift_signals),
        )
        object.__setattr__(
            self, "behavioural_repair_actions",
            list(self.behavioural_repair_actions),
        )


# ── 2.7.5 — TemporalTrace ───────────────────────────────────────────────────


@dataclass(frozen=True)
class TemporalTrace:
    """
    Per‑segment temporal trace persisted across cycles.

    Constructed after progress detection, temporal drift signals,
    classification, and repair in Phase 2.7.1–2.7.4.

    All fields are JSON‑safe.  Defensive copies prevent external mutation.
    """

    progress_deltas: Dict[str, Any]
    stall_reasons: List[str]
    oscillation_markers: List[str]

    def __post_init__(self) -> None:
        ensure_json_pure(self.progress_deltas)
        object.__setattr__(
            self, "progress_deltas", copy.deepcopy(self.progress_deltas)
        )
        object.__setattr__(
            self, "stall_reasons", list(self.stall_reasons)
        )
        object.__setattr__(
            self, "oscillation_markers", list(self.oscillation_markers)
        )


# ── 2.8.5 — SemanticTrace ───────────────────────────────────────────────────


@dataclass(frozen=True)
class SemanticTrace:
    """
    Per‑segment semantic trace persisted across cycles.

    Constructed after semantic validation, semantic drift signals,
    classification, and repair in Phase 2.8.1–2.8.4.

    All fields are JSON‑safe.  Defensive copies prevent external mutation.
    """

    semantic_mismatches: List[Dict[str, Any]]
    semantic_repair_actions: List[str]
    semantic_drift_history: List[Dict[str, Any]]

    def __post_init__(self) -> None:
        for item in self.semantic_mismatches:
            ensure_json_pure(item)
        for item in self.semantic_drift_history:
            ensure_json_pure(item)
        object.__setattr__(
            self, "semantic_mismatches",
            [copy.deepcopy(item) for item in self.semantic_mismatches],
        )
        object.__setattr__(
            self, "semantic_repair_actions",
            list(self.semantic_repair_actions),
        )
        object.__setattr__(
            self, "semantic_drift_history",
            [copy.deepcopy(item) for item in self.semantic_drift_history],
        )


# ── 2.9.5 — DriftTrace ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class DriftTrace:
    """
    Per‑segment unified drift trace persisted across cycles.

    Constructed after unified drift signals (2.9.1), classification (2.9.2),
    confirmation (2.9.3), and recovery (2.9.4).

    All fields are JSON‑safe.  Defensive copies prevent external mutation.
    """

    unified_drift_history: List[Dict[str, Any]]
    drift_confidence_evolution: List[float]
    drift_recovery_decisions: List[Dict[str, Any]]

    def __post_init__(self) -> None:
        for item in self.unified_drift_history:
            ensure_json_pure(item)
        for item in self.drift_recovery_decisions:
            ensure_json_pure(item)
        object.__setattr__(
            self, "unified_drift_history",
            [copy.deepcopy(item) for item in self.unified_drift_history],
        )
        object.__setattr__(
            self, "drift_confidence_evolution",
            list(self.drift_confidence_evolution),
        )
        object.__setattr__(
            self, "drift_recovery_decisions",
            [copy.deepcopy(item) for item in self.drift_recovery_decisions],
        )

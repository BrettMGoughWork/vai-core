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

"""
Phase 2.6.6 — Behavioural Trace Types
====================================

``BehaviouralTrace`` is a frozen, JSON‑safe dataclass that persists per‑segment
behavioural information across cycles.

It is constructed **after** classification and repair in Phase 2.6.4 / 2.6.5.

Fields
------
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

"""
Phase 2.6.4 — Behavioural Drift Classifier
==========================================

Maps per‑segment ``BehaviouralSignal``\\ s (emitted by the 2.6.3 detectors) into a
``BehaviouralDriftClassification`` that summarises the drift status and
confidence for a single segment.

The classifier is **pure** and **deterministic**:

- No LLM calls, no tool calls, no I/O.
- Does not mutate the ``SegmentMemoryRecord``.
- Does not use the cross‑cycle ``ConfirmationBuffer`` (that is 2.5.3).
- Multi‑cycle confirmation is a simple streak heuristic stored in
  ``record.metadata["behavioural_drift_streak"]``.

Confidence formula

::

    base_confidence = len(signals) / 4
    streak_bonus    = 0.1 * consecutive_count
    confidence      = min(1.0, base_confidence + streak_bonus)

Where *consecutive_count* is read from metadata (defaults to 0 if absent).
"""
from __future__ import annotations

from typing import List

from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.planning.drift.behavioural_signal_types import (
    BehaviouralDriftClassification,
    BehaviouralSignal,
)

# ── confidence formula constants ─────────────────────────────────────────────
_MAX_SIGNAL_TYPES = 4  # denominator for base confidence
_STREAK_MULTIPLIER = 0.1  # bonus per consecutive cycle
_STREAK_METADATA_KEY = "behavioural_drift_streak"


def classify_behavioural_drift(
    record: SegmentMemoryRecord,
) -> BehaviouralDriftClassification:
    """
    Classify behavioural drift for a single segment record.

    Returns a ``BehaviouralDriftClassification`` with:

    * ``drift_status`` — ``"no_drift"`` if ``behavioural_signals`` is empty,
      otherwise ``"behavioural_drift"``.
    * ``confidence`` — a float in ``[0.0, 1.0]`` computed from the number of
      signals and the streak counter.
    * ``reasons`` — the list of ``BehaviouralSignal``\\ s that triggered the
      classification (empty for no‑drift).

    The streak counter is read from
    ``record.metadata["behavioural_drift_streak"]`` and defaults to 0 when
    absent.
    """
    signals: List[BehaviouralSignal] = record.behavioural_signals

    # ── no signals → no drift ──────────────────────────────────────────
    if not signals:
        return BehaviouralDriftClassification(
            drift_status="no_drift",
            confidence=0.0,
            reasons=[],
        )

    # ── compute confidence ─────────────────────────────────────────────
    base_confidence = len(signals) / _MAX_SIGNAL_TYPES  # 0.0 … 1.0

    streak_raw = record.metadata.get(_STREAK_METADATA_KEY, 0)
    try:
        consecutive_count = int(streak_raw)
    except (TypeError, ValueError):
        consecutive_count = 0

    streak_bonus = _STREAK_MULTIPLIER * max(0, consecutive_count)
    confidence = min(1.0, base_confidence + streak_bonus)

    # ── round to avoid floating‑point noise ────────────────────────────
    confidence = round(confidence, 10)

    return BehaviouralDriftClassification(
        drift_status="behavioural_drift",
        confidence=confidence,
        reasons=list(signals),  # defensive copy
    )

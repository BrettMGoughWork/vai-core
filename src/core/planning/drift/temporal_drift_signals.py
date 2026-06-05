"""
Phase 2.7.2 — Temporal Drift Signals
====================================

Detects multi‑cycle temporal anomalies by comparing two consecutive
``SegmentMemoryRecord`` instances and the ``ProgressSignal`` from 2.7.1.

Signal types
------------
- **no_progress** — progress_signal is ``stalled`` (confidence 0.6).
- **repetition** — current output is structurally identical to previous
  output (confidence 0.7).
- **oscillation** — output bounces between two states (confidence 0.8).
- **regression** — progress_signal is ``regressed`` (confidence 0.9).

The detector is **pure**, **deterministic**, and never mutates its inputs.
Signals are emitted in a deterministic order: no_progress, repetition,
oscillation, regression.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.planning.drift.temporal_signal_types import (
    ProgressSignal,
    TemporalDriftSignal,
)


# ── helpers ─────────────────────────────────────────────────────────────────


def _deep_eq(a: Any, b: Any) -> bool:
    """Deep structural equality for JSON‑safe values."""
    return a == b


def _structural_hash(value: Any) -> str:
    """Return a stable SHA‑256 hash of a JSON‑safe value."""
    raw = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ── signal detection ────────────────────────────────────────────────────────


def _detect_no_progress(
    previous_record: SegmentMemoryRecord,
    current_record: SegmentMemoryRecord,
    progress_signal: ProgressSignal,
) -> Optional[TemporalDriftSignal]:
    """Emit ``no_progress`` when progress_signal is stalled."""
    if progress_signal.status != "stalled":
        return None

    details: Dict[str, Any] = {
        "status": "stalled",
        "delta_summary": list(progress_signal.reasons),
    }
    return TemporalDriftSignal(
        type="no_progress",
        confidence=0.6,
        details=details,
    )


def _detect_repetition(
    previous_record: SegmentMemoryRecord,
    current_record: SegmentMemoryRecord,
) -> Optional[TemporalDriftSignal]:
    """Emit ``repetition`` when current output equals previous output."""
    if not _deep_eq(previous_record.last_output, current_record.last_output):
        return None

    details: Dict[str, Any] = {
        "hash": _structural_hash(current_record.last_output),
        "match": "current output is structurally identical to previous output",
    }
    return TemporalDriftSignal(
        type="repetition",
        confidence=0.7,
        details=details,
    )


def _detect_oscillation(
    previous_record: SegmentMemoryRecord,
    current_record: SegmentMemoryRecord,
) -> Optional[TemporalDriftSignal]:
    """
    Emit ``oscillation`` when the output alternates between two states.

    Condition: current output equals previous output **and** the
    ``last_output`` stored in previous metadata matches the
    ``second_last_output`` in current metadata (indicating a flip‑flop
    pattern A → B → A).
    """
    # Both conditions required for oscillation
    if not _deep_eq(previous_record.last_output, current_record.last_output):
        return None

    prev_metadata: Dict[str, Any] = previous_record.metadata
    curr_metadata: Dict[str, Any] = current_record.metadata

    prev_last = prev_metadata.get("last_output") if isinstance(prev_metadata, dict) else None
    curr_second_last = curr_metadata.get("second_last_output") if isinstance(curr_metadata, dict) else None

    # If either metadata key is missing, oscillation cannot be confirmed
    if prev_last is None and curr_second_last is None:
        return None
    if prev_last is None or curr_second_last is None:
        return None

    if not _deep_eq(prev_last, curr_second_last):
        return None

    details: Dict[str, Any] = {
        "pattern": "A → B → A oscillation detected",
        "current_hash": _structural_hash(current_record.last_output),
        "alternate_hash": _structural_hash(prev_last),
    }
    return TemporalDriftSignal(
        type="oscillation",
        confidence=0.8,
        details=details,
    )


def _detect_regression(
    progress_signal: ProgressSignal,
) -> Optional[TemporalDriftSignal]:
    """Emit ``regression`` when progress_signal is regressed."""
    if progress_signal.status != "regressed":
        return None

    details: Dict[str, Any] = {
        "status": "regressed",
        "delta_summary": list(progress_signal.reasons),
        "confidence": progress_signal.confidence,
    }
    return TemporalDriftSignal(
        type="regression",
        confidence=0.9,
        details=details,
    )


# ── public API ──────────────────────────────────────────────────────────────


def detect_temporal_drift(
    previous_record: Optional[SegmentMemoryRecord],
    current_record: SegmentMemoryRecord,
    progress_signal: Optional[ProgressSignal],
) -> List[TemporalDriftSignal]:
    """
    Detect multi‑cycle temporal anomalies between two segment records.

    Args:
        previous_record:
            The prior segment record.  ``None`` on first cycle — returns
            ``[]`` (no temporal context available).
        current_record:
            The current segment record.
        progress_signal:
            The progress signal from 2.7.1.  ``None`` if ``previous_record``
            was ``None``.

    Returns:
        A deterministic, ordered list of ``TemporalDriftSignal`` objects.
        Order: ``no_progress``, ``repetition``, ``oscillation``,
        ``regression``.
    """
    if previous_record is None:
        return []

    if progress_signal is None:
        return []

    signals: List[TemporalDriftSignal] = []

    # Detectors are called in deterministic order
    for detector_fn in (
        _detect_no_progress,
        _detect_repetition,
        _detect_oscillation,
        _detect_regression,
    ):
        if detector_fn is _detect_no_progress:
            signal = detector_fn(previous_record, current_record, progress_signal)
        elif detector_fn is _detect_regression:
            signal = detector_fn(progress_signal)
        else:
            signal = detector_fn(previous_record, current_record)
        if signal is not None:
            signals.append(signal)

    return signals

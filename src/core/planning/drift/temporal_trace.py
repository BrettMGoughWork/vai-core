"""
Phase 2.7.5 — Temporal Trace Builder
====================================

Constructs a ``TemporalTrace`` from two consecutive segment records,
a progress signal (2.7.1), temporal drift signals (2.7.2),
a temporal drift classification (2.7.3), and a temporal repair plan (2.7.4).

The trace is **pure**, **deterministic**, and never mutates its inputs.

Trace Components
----------------
progress_deltas
    Structural diffs (output, metadata, side‑effects) computed via
    ``_structural_diff``, the same pure helper used in 2.7.1.

stall_reasons
    Extracted deterministically from:
    - ``ProgressSignal.status == "stalled"`` → progress‑level reasons
    - ``TemporalDriftSignal`` of type ``"no_progress"`` → drift‑level details

oscillation_markers
    Extracted deterministically from ``TemporalDriftSignal`` of type
    ``"oscillation"``.  Each marker includes the oscillation pattern details.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.planning.drift.segment_trace_types import TemporalTrace
from src.core.planning.drift.temporal_signal_types import (
    ProgressSignal,
    TemporalDriftClassification,
    TemporalDriftSignal,
    TemporalRepairPlan,
)


# ── structural diff ──────────────────────────────────────────────────────────


def _structural_diff(prev: Any, curr: Any) -> Dict[str, Any]:
    """
    Compute a JSON‑safe structural diff between two values.

    - If both are ``dict``, returns a diff with ``added``, ``removed``, and
      ``changed`` keys.
    - Otherwise returns ``{"previous": prev, "current": curr}``.

    Always returns a dict.  Keys are iterated in deterministic (sorted) order.
    """
    if isinstance(prev, dict) and isinstance(curr, dict):
        added: Dict[str, Any] = {}
        removed: Dict[str, Any] = {}
        changed: Dict[str, Any] = {}

        all_keys = set(prev.keys()) | set(curr.keys())

        for key in sorted(all_keys):
            if key not in prev:
                added[key] = curr[key]
            elif key not in curr:
                removed[key] = prev[key]
            elif prev[key] != curr[key]:
                changed[key] = {"old": prev[key], "new": curr[key]}

        return {
            "added": added,
            "removed": removed,
            "changed": changed,
        }
    else:
        return {"previous": prev, "current": curr}


# ── side‑effects delta ──────────────────────────────────────────────────────


def _compute_side_effects_delta(
    previous_record: SegmentMemoryRecord,
    current_record: SegmentMemoryRecord,
) -> Dict[str, Any]:
    """
    Compute a deterministic side‑effects delta between two records.

    Returns ``{"previous_count": N, "current_count": M, "net_change": M - N}``.
    """
    from src.core.planning.drift.behavioural_signal_types import (
        BehaviouralSignalType,
    )

    prev_count = sum(
        1
        for s in previous_record.behavioural_signals
        if s.signal_type == BehaviouralSignalType.UNEXPECTED_SIDE_EFFECT
    )
    curr_count = sum(
        1
        for s in current_record.behavioural_signals
        if s.signal_type == BehaviouralSignalType.UNEXPECTED_SIDE_EFFECT
    )
    return {
        "previous_count": prev_count,
        "current_count": curr_count,
        "net_change": curr_count - prev_count,
    }


# ── stall reasons extraction ────────────────────────────────────────────────


def _extract_stall_reasons(
    progress_signal: Optional[ProgressSignal],
    temporal_signals: List[TemporalDriftSignal],
) -> List[str]:
    """
    Extract stall reasons deterministically from progress and temporal signals.

    Returns a sorted list of JSON‑safe, human‑readable strings.
    """
    reasons: List[str] = []

    # From progress signal: if stalled, include its reasons
    if progress_signal is not None and progress_signal.status == "stalled":
        for reason in progress_signal.reasons:
            reasons.append(f"progress stalled: {reason}")

    # From temporal drift signals: no_progress details
    for signal in temporal_signals:
        if signal.type == "no_progress":
            summary = signal.details.get("summary", "no progress detected")
            reasons.append(f"temporal drift: {summary}")

    # Deterministic ordering
    return sorted(reasons)


# ── oscillation markers extraction ──────────────────────────────────────────


def _extract_oscillation_markers(
    temporal_signals: List[TemporalDriftSignal],
) -> List[str]:
    """
    Extract oscillation markers deterministically from temporal drift signals.

    Each marker is a JSON‑safe, human‑readable string describing the
    oscillation pattern detected.
    """
    markers: List[str] = []

    for signal in temporal_signals:
        if signal.type == "oscillation":
            pattern = signal.details.get("pattern", "unknown pattern")
            markers.append(f"oscillation detected: {pattern}")

    # Deterministic ordering
    return sorted(markers)


# ── public API ───────────────────────────────────────────────────────────────


def build_temporal_trace(
    previous_record: Optional[SegmentMemoryRecord],
    current_record: SegmentMemoryRecord,
    progress_signal: Optional[ProgressSignal],
    temporal_signals: List[TemporalDriftSignal],
    temporal_classification: TemporalDriftClassification,
    temporal_repair: TemporalRepairPlan,
) -> TemporalTrace:
    """
    Build a per‑segment temporal trace from consecutive records and
    temporal‑reasoning outputs.

    Args:
        previous_record:
            The prior segment record.  ``None`` on first cycle — deltas are
            computed against empty values.
        current_record:
            The current segment record.
        progress_signal:
            The progress signal from 2.7.1 (``None`` when no temporal context).
        temporal_signals:
            The temporal drift signals from 2.7.2.
        temporal_classification:
            The temporal drift classification from 2.7.3.
        temporal_repair:
            The temporal repair plan from 2.7.4.

    Returns:
        A ``TemporalTrace`` with pure, defensive‑copied data.
    """
    # ── output delta ─────────────────────────────────────────────────────
    prev_output: Any = (
        previous_record.last_output if previous_record is not None else None
    )
    curr_output: Any = current_record.last_output
    output_delta = _structural_diff(prev_output, curr_output)

    # ── metadata delta ───────────────────────────────────────────────────
    prev_metadata: Dict[str, Any] = (
        previous_record.metadata if previous_record is not None else {}
    )
    curr_metadata: Dict[str, Any] = current_record.metadata
    metadata_delta = _structural_diff(prev_metadata, curr_metadata)

    # ── side‑effects delta ──────────────────────────────────────────────
    if previous_record is not None:
        se_delta: Any = _compute_side_effects_delta(previous_record, current_record)
    else:
        se_delta = None

    # ── build progress_deltas ────────────────────────────────────────────
    progress_deltas: Dict[str, Any] = {
        "output_delta": output_delta,
        "metadata_delta": metadata_delta,
    }
    if se_delta is not None:
        progress_deltas["side_effects_delta"] = se_delta

    # ── extract stall reasons and oscillation markers ────────────────────
    stall_reasons = _extract_stall_reasons(progress_signal, temporal_signals)
    oscillation_markers = _extract_oscillation_markers(temporal_signals)

    return TemporalTrace(
        progress_deltas=progress_deltas,
        stall_reasons=stall_reasons,
        oscillation_markers=oscillation_markers,
    )

"""
Phase 2.6.6 — Behavioural Trace Builder
======================================

Constructs a ``BehaviouralTrace`` from two consecutive segment records,
a classification (2.6.4), and a repair plan (2.6.5).

The trace is **pure**, **deterministic**, and never mutates its inputs.

Deltas
------
Structural diffs are computed via ``_structural_diff``, a pure helper that
compares two JSON‑safe values and returns a ``{"added": ..., "removed": ...,
"changed": ...}`` dict.  Non‑dict values (including ``None``) are compared
directly without diff decomposition.

Side‑effects deltas are extracted from ``UNEXPECTED_SIDE_EFFECT`` signals
in the classification's reasons.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.planning.drift.behavioural_signal_types import (
    BehaviouralDriftClassification,
    BehaviouralDriftRepair,
    BehaviouralSignalType,
)
from src.core.planning.drift.segment_trace_types import BehaviouralTrace


# ── structural diff ──────────────────────────────────────────────────────────


def _structural_diff(prev: Any, curr: Any) -> Dict[str, Any]:
    """
    Compute a JSON‑safe structural diff between two values.

    - If both are ``dict``, returns a diff with ``added``, ``removed``, and
      ``changed`` keys.
    - Otherwise returns ``{"previous": prev, "current": curr}``.

    Always returns a dict.
    """
    if isinstance(prev, dict) and isinstance(curr, dict):
        added: Dict[str, Any] = {}
        removed: Dict[str, Any] = {}
        changed: Dict[str, Any] = {}

        all_keys = set(prev.keys()) | set(curr.keys())

        for key in all_keys:
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


def _extract_side_effects_delta(
    classification: BehaviouralDriftClassification,
) -> Optional[Dict[str, Any]]:
    """Extract side-effect delta from UNEXPECTED_SIDE_EFFECT signals (if any)."""
    for signal in classification.reasons:
        if signal.signal_type == BehaviouralSignalType.UNEXPECTED_SIDE_EFFECT:
            return dict(signal.details)
    return None


# ── public API ───────────────────────────────────────────────────────────────


def build_behavioural_trace(
    previous_record: Optional[SegmentMemoryRecord],
    current_record: SegmentMemoryRecord,
    classification: BehaviouralDriftClassification,
    repair: BehaviouralDriftRepair,
) -> BehaviouralTrace:
    """
    Build a per‑segment behavioural trace from two consecutive records.

    Args:
        previous_record: the prior segment record (may be ``None`` on first
                         cycle — deltas are computed against empty values).
        current_record:  the current segment record.
        classification:  the 2.6.4 drift classification.
        repair:          the 2.6.5 repair plan.

    Returns:
        A ``BehaviouralTrace`` with pure, defensive‑copied data.
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

    # ── side-effects delta ──────────────────────────────────────────────
    side_effects_delta = _extract_side_effects_delta(classification)

    behavioural_deltas: Dict[str, Any] = {
        "output_delta": output_delta,
        "metadata_delta": metadata_delta,
    }
    if side_effects_delta is not None:
        behavioural_deltas["side_effects_delta"] = side_effects_delta

    return BehaviouralTrace(
        behavioural_deltas=behavioural_deltas,
        behavioural_drift_signals=list(classification.reasons),
        behavioural_repair_actions=list(repair.repair_actions),
    )

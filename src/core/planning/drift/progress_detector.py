"""
Phase 2.7.1 — Progress Detector
==============================

Compares two consecutive ``SegmentMemoryRecord`` instances and produces a
``ProgressSignal`` classifying the segment as *steady*, *stalled*, or
*regressed*.

Logic
-----
1. If ``previous_record`` is ``None`` → ``None`` (no temporal context).
2. Compute structural diffs for output, metadata, and side‑effects.
3. Classify based on the balance of additions vs removals/changes.
4. Attach deterministic reasons and a fixed confidence per status.

The detector is **pure**, **deterministic**, and never mutates its inputs.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.planning.drift.behavioural_signal_types import (
    BehaviouralSignalType,
)
from src.core.planning.drift.temporal_signal_types import ProgressSignal


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


# ── delta counting ───────────────────────────────────────────────────────────


def _count_delta(delta: Dict[str, Any]) -> Tuple[int, int, int]:
    """
    Return ``(added_count, removed_count, changed_count)`` from a structural
    diff.

    Handles both dict‑diff format (``added`` / ``removed`` / ``changed``
    keys) and simple‑value format (``previous`` / ``current`` keys).
    """
    if "added" in delta:
        # Dict diff format — count the items
        return (
            len(delta.get("added", {})),
            len(delta.get("removed", {})),
            len(delta.get("changed", {})),
        )
    else:
        # Simple value format — compare previous and current
        prev = delta.get("previous")
        curr = delta.get("current")
        if prev == curr:
            return (0, 0, 0)
        if prev is None and curr is not None:
            return (1, 0, 0)  # new value → progress
        if prev is not None and curr is None:
            return (0, 1, 0)  # lost value → regression
        # Both non‑None, different
        return (0, 0, 1)


# ── side‑effects delta ──────────────────────────────────────────────────────


def _side_effects_delta(
    previous_record: SegmentMemoryRecord,
    current_record: SegmentMemoryRecord,
) -> int:
    """
    Return the net change in unexpected side‑effect signals.

    Positive → more side effects in current (regression indicator).
    Negative → fewer side effects in current (progress indicator).
    Zero     → no change.
    """
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
    return curr_count - prev_count


# ── classification ───────────────────────────────────────────────────────────


def _classify(
    output_delta: Dict[str, Any],
    metadata_delta: Dict[str, Any],
    se_delta: int,
) -> Tuple[str, List[str]]:
    """
    Classify progress status from structural deltas and side‑effects delta.

    Returns ``(status, reasons)``.
    """
    out_a, out_r, out_c = _count_delta(output_delta)
    meta_a, meta_r, meta_c = _count_delta(metadata_delta)

    # Side‑effects: more side effects = negative, fewer = positive
    se_positive = max(0, -se_delta)  # fewer side effects → positive
    se_negative = max(0, se_delta)   # more side effects → negative

    total_positive = out_a + meta_a + se_positive
    total_negative = out_r + out_c + meta_r + meta_c + se_negative

    # Build reasons deterministically (sorted)
    reasons: List[str] = []
    if out_a > 0:
        reasons.append(f"output: {out_a} field(s) added")
    if out_r > 0:
        reasons.append(f"output: {out_r} field(s) removed")
    if out_c > 0:
        reasons.append(f"output: {out_c} field(s) changed")
    if meta_a > 0:
        reasons.append(f"metadata: {meta_a} field(s) added")
    if meta_r > 0:
        reasons.append(f"metadata: {meta_r} field(s) removed")
    if meta_c > 0:
        reasons.append(f"metadata: {meta_c} field(s) changed")
    if se_negative > 0:
        reasons.append(
            f"side effects: {se_negative} new unexpected side effect(s)"
        )
    if se_positive > 0:
        reasons.append(
            f"side effects: {se_positive} unexpected side effect(s) resolved"
        )

    if total_positive == 0 and total_negative == 0:
        return "stalled", reasons

    if total_positive > total_negative:
        return "steady", reasons
    elif total_negative > total_positive:
        return "regressed", reasons
    else:
        # Equal — no net progress
        return "stalled", reasons


# ── public API ───────────────────────────────────────────────────────────────


_CONFIDENCE: Dict[str, float] = {
    "steady": 0.7,
    "stalled": 0.5,
    "regressed": 0.9,
}


def detect_progress(
    previous_record: Optional[SegmentMemoryRecord],
    current_record: SegmentMemoryRecord,
) -> Optional[ProgressSignal]:
    """
    Compare two consecutive segment records and classify progress.

    Args:
        previous_record:
            The prior segment record.  ``None`` on first cycle — returns
            ``None``.
        current_record:
            The current segment record.

    Returns:
        A ``ProgressSignal`` with status, confidence, and reasons, or
        ``None`` if no temporal context is available.
    """
    if previous_record is None:
        return None

    # Compute structural diffs
    output_delta = _structural_diff(
        previous_record.last_output,
        current_record.last_output,
    )
    metadata_delta = _structural_diff(
        previous_record.metadata,
        current_record.metadata,
    )
    se_delta = _side_effects_delta(previous_record, current_record)

    status, reasons = _classify(output_delta, metadata_delta, se_delta)

    return ProgressSignal(
        status=status,
        confidence=_CONFIDENCE[status],
        reasons=reasons,
    )

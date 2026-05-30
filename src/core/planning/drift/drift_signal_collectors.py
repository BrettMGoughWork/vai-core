from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from src.core.planning.drift.drift_context import DriftContext
from src.core.planning.drift.drift_types import DriftSignal, DriftSignalClass


# ---------------------------------------------------------------------------
# Thresholds — all deterministic, no heuristics
# ---------------------------------------------------------------------------

TRANSITION_FAILURE_THRESHOLD: int = 3
REPAIR_LOOP_THRESHOLD: int = 3
FALLBACK_THRESHOLD: int = 2

STALE_THRESHOLD_MS: int = 3_600_000  # 1 hour

STATE_TIME_THRESHOLDS_MS: dict = {
    "running":  300_000,   # 5 minutes
    "blocked":   60_000,   # 1 minute
    "retrying": 120_000,   # 2 minutes
    "active":   600_000,   # 10 minutes
}

DRIFT_WINDOW: int = 5
DRIFT_REPEAT_THRESHOLD: int = 3

FUTURE_TOLERANCE_MS: int = 60_000   # 1 minute ahead of ctx.timestamp is still OK

# signal_type value used by FullDriftDetector when writing to DriftMemory
DRIFT_SIGNAL_TYPE: str = "full_drift"


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _iso_from_ms(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat()


def _parse_iso_to_ms(iso: str) -> int:
    """Parse an ISO 8601 string to ms.  Returns -1 on failure."""
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return -1


def _signal(
    sig_type: str,
    severity: str,
    ts_ms: int,
    cls: DriftSignalClass,
    meta: dict,
) -> DriftSignal:
    return DriftSignal(
        type=sig_type,
        severity=severity,
        timestamp=_iso_from_ms(ts_ms),
        signal_class=cls.value,
        metadata=meta,
    )


# ---------------------------------------------------------------------------
# Structural signal collector
# ---------------------------------------------------------------------------

def collect_structural_signals(ctx: DriftContext) -> List[DriftSignal]:
    """
    Inspect the memory substrate for structural integrity violations.

    All checks are pure reads against ctx — no side effects.
    """
    signals: List[DriftSignal] = []
    cls = DriftSignalClass.STRUCTURAL
    ts = ctx.timestamp

    # ── Missing segments ────────────────────────────────────────────────────
    # Plan references a segment_id that is not present in segment_records.
    if ctx.plan_id and ctx.plan_id in ctx.plan_records:
        plan = ctx.plan_records[ctx.plan_id]
        for seg_id in plan.segments:
            if seg_id not in ctx.segment_records:
                signals.append(_signal(
                    "missing_segment", "high", ts, cls,
                    {"segment_id": seg_id, "plan_id": ctx.plan_id},
                ))

    # ── Broken parent chains ────────────────────────────────────────────────
    # Segment references a parent_id that is not in segment_records.
    for seg_id, seg in ctx.segment_records.items():
        if seg.parent_id and seg.parent_id not in ctx.segment_records:
            signals.append(_signal(
                "broken_parent_chain", "high", ts, cls,
                {"segment_id": seg_id, "parent_id": seg.parent_id},
            ))

    # ── Invalid subgoal → segment mappings ──────────────────────────────────
    # Segment belongs to a different subgoal_id than ctx.subgoal_id.
    for seg_id, seg in ctx.segment_records.items():
        if seg.subgoal_id and seg.subgoal_id != ctx.subgoal_id:
            signals.append(_signal(
                "invalid_subgoal_segment_mapping", "medium", ts, cls,
                {"segment_id": seg_id, "expected": ctx.subgoal_id, "actual": seg.subgoal_id},
            ))

    # ── Stale / unparseable timestamps ──────────────────────────────────────
    # Segment or plan created_at cannot be parsed as ISO 8601.
    for seg_id, seg in ctx.segment_records.items():
        if _parse_iso_to_ms(seg.created_at) == -1:
            signals.append(_signal(
                "stale_timestamp", "low", ts, cls,
                {"record_type": "segment", "segment_id": seg_id, "created_at": seg.created_at},
            ))
    for plan_id, plan in ctx.plan_records.items():
        if _parse_iso_to_ms(plan.created_at) == -1:
            signals.append(_signal(
                "stale_timestamp", "low", ts, cls,
                {"record_type": "plan", "plan_id": plan_id, "created_at": plan.created_at},
            ))

    # ── Orphaned subgoals ───────────────────────────────────────────────────
    # Subgoal has a parent_id that doesn't resolve to any known subgoal record.
    for sg_id, sg in ctx.subgoal_records.items():
        if sg.parent_id and sg.parent_id not in ctx.subgoal_records:
            signals.append(_signal(
                "orphaned_subgoal", "medium", ts, cls,
                {"subgoal_id": sg_id, "missing_parent_id": sg.parent_id},
            ))

    # ── Invalid plan references ─────────────────────────────────────────────
    # Plan's subgoal_id is not present in subgoal_records.
    for plan_id, plan in ctx.plan_records.items():
        if plan.subgoal_id and plan.subgoal_id not in ctx.subgoal_records:
            signals.append(_signal(
                "invalid_plan_reference", "high", ts, cls,
                {"plan_id": plan_id, "missing_subgoal_id": plan.subgoal_id},
            ))

    return signals


# ---------------------------------------------------------------------------
# Behavioural signal collector
# ---------------------------------------------------------------------------

def collect_behavioural_signals(ctx: DriftContext) -> List[DriftSignal]:
    """
    Inspect execution history for behavioural anomalies.

    All checks are pure reads against ctx — no side effects.
    """
    signals: List[DriftSignal] = []
    cls = DriftSignalClass.BEHAVIOURAL
    ts = ctx.timestamp

    # ── Governance violations ────────────────────────────────────────────────
    for v in ctx.governance_violations:
        signals.append(_signal(
            "governance_violation", "medium", ts, cls,
            {"rule": v.rule, "field": v.field, "message": v.message},
        ))

    # ── Repeated transition failures ─────────────────────────────────────────
    for tf in ctx.transition_failures:
        if tf.count >= TRANSITION_FAILURE_THRESHOLD:
            signals.append(_signal(
                "repeated_transition_failure", "high", ts, cls,
                {"from_state": tf.from_state, "event": tf.event, "count": tf.count},
            ))

    # ── Repair loop ───────────────────────────────────────────────────────────
    if ctx.repair_attempts >= REPAIR_LOOP_THRESHOLD:
        signals.append(_signal(
            "repair_loop", "high", ts, cls,
            {"repair_attempts": ctx.repair_attempts, "threshold": REPAIR_LOOP_THRESHOLD},
        ))

    # ── Fallback overuse ──────────────────────────────────────────────────────
    if ctx.fallback_count >= FALLBACK_THRESHOLD:
        signals.append(_signal(
            "fallback_overuse", "medium", ts, cls,
            {"fallback_count": ctx.fallback_count, "threshold": FALLBACK_THRESHOLD},
        ))

    return signals


# ---------------------------------------------------------------------------
# Temporal signal collector
# ---------------------------------------------------------------------------

def collect_temporal_signals(ctx: DriftContext) -> List[DriftSignal]:
    """
    Inspect timestamps and DriftMemory for temporal anomalies.

    Reads from ctx.drift_memory but NEVER writes to it.
    All checks are pure reads — no side effects.
    """
    signals: List[DriftSignal] = []
    cls = DriftSignalClass.TEMPORAL
    ts = ctx.timestamp

    # ── Excessive time in a state ─────────────────────────────────────────────
    for sg_id, sg in ctx.subgoal_records.items():
        threshold_ms = STATE_TIME_THRESHOLDS_MS.get(sg.state)
        if threshold_ms is not None:
            age_ms = ts - sg.created_at
            if age_ms > threshold_ms:
                signals.append(_signal(
                    "excessive_state_time", "medium", ts, cls,
                    {
                        "subgoal_id": sg_id,
                        "state": sg.state,
                        "age_ms": age_ms,
                        "threshold_ms": threshold_ms,
                    },
                ))

    # ── Stale memory entries ──────────────────────────────────────────────────
    for sg_id, sg in ctx.subgoal_records.items():
        if (ts - sg.created_at) > STALE_THRESHOLD_MS:
            signals.append(_signal(
                "stale_memory_entry", "low", ts, cls,
                {"subgoal_id": sg_id, "age_ms": ts - sg.created_at, "threshold_ms": STALE_THRESHOLD_MS},
            ))

    # ── Out-of-order timestamps ───────────────────────────────────────────────
    # Child segment's created_at precedes its parent's created_at.
    for seg_id, seg in ctx.segment_records.items():
        if seg.parent_id and seg.parent_id in ctx.segment_records:
            parent = ctx.segment_records[seg.parent_id]
            child_ms = _parse_iso_to_ms(seg.created_at)
            parent_ms = _parse_iso_to_ms(parent.created_at)
            if child_ms != -1 and parent_ms != -1 and child_ms < parent_ms:
                signals.append(_signal(
                    "out_of_order_timestamp", "medium", ts, cls,
                    {
                        "segment_id": seg_id,
                        "parent_id": seg.parent_id,
                        "child_created_at": seg.created_at,
                        "parent_created_at": parent.created_at,
                    },
                ))

    # ── Future timestamps ─────────────────────────────────────────────────────
    # Segment created_at is ahead of ctx.timestamp beyond tolerance.
    for seg_id, seg in ctx.segment_records.items():
        seg_ms = _parse_iso_to_ms(seg.created_at)
        if seg_ms != -1 and seg_ms > ts + FUTURE_TOLERANCE_MS:
            signals.append(_signal(
                "future_timestamp", "medium", ts, cls,
                {
                    "segment_id": seg_id,
                    "created_at": seg.created_at,
                    "anchor_ms": ts,
                    "skew_ms": seg_ms - ts,
                },
            ))

    # ── Repeated drift in window ──────────────────────────────────────────────
    # DriftMemory shows >= DRIFT_REPEAT_THRESHOLD full_drift events in recent window.
    if ctx.drift_memory is not None:
        count = ctx.drift_memory.count_recent(DRIFT_SIGNAL_TYPE, DRIFT_WINDOW)
        if count >= DRIFT_REPEAT_THRESHOLD:
            signals.append(_signal(
                "repeated_drift_in_window", "high", ts, cls,
                {"count": count, "window": DRIFT_WINDOW, "threshold": DRIFT_REPEAT_THRESHOLD},
            ))

    return signals

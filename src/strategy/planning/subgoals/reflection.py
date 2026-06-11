"""
Phase 2.12.2 — Subgoal Reflection
==================================

Deterministic, pure‑function reflection logic for subgoal‑level execution.

Reflection evaluates:
- subgoal progress (structural summary)
- subgoal drift (reuses existing drift classifier)
- subgoal repair (reuses existing repair engine)
- subgoal completion (boolean predicate)

Constraints
-----------
- Pure functions only — no side effects, no mutation of inputs.
- No I/O, no inference, no LLM calls.
- Deterministic — identical inputs always produce identical outputs.
- JSON‑safe — all output structures are serialisable to JSON.
- Reuses the existing drift + repair substrate from
  ``src.strategy.planning.drift.*`` and ``repair_action_library``.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.strategy.planning.drift.repair_action_library import repair_subgoal
from src.strategy.planning.drift.unified_drift_classifier import classify_unified_drift
from src.strategy.planning.drift.unified_drift_types import (
    UnifiedDriftClassification,
    UnifiedDriftSignal,
)
from src.strategy.types.plan_segment import PlanSegment
from src.strategy.types.subgoal import Subgoal, SubgoalLifecycleState


# ──────────────────────────────────────────────────────────────────────────────
# SubgoalReflectionResult
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SubgoalReflectionResult:
    """Deterministic reflection result for a single subgoal.

    Fields
    ------
    progress
        Structural summary dict with ``segment_count``, ``completed_segments``,
        ``missing_fields``, and ``malformed_segments`` keys.
    drift
        Dict snapshot of the ``UnifiedDriftClassification`` produced by
        running the existing drift classifier on the subgoal.
    repair
        Dict with ``action`` (``"none"``, ``"repair_subgoal"``, or
        ``"repair_failed"``) and ``repaired`` (the subgoal dict after repair).
    is_complete
        ``True`` when the subgoal has no missing fields, all segments complete,
        and no drift requiring repair.
    """
    progress: dict
    drift: dict
    repair: dict
    is_complete: bool


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _subgoal_to_raw_dict(subgoal: Subgoal) -> Dict[str, Any]:
    """Convert a Subgoal to a raw dict for structural inspection.

    Never mutates the input — returns a fresh dict.
    """
    return {
        "subgoal_id": subgoal.subgoal_id,
        "goal": subgoal.goal,
        "context": subgoal.context,
        "metadata": subgoal.metadata,
        "parent_id": subgoal.parent_id,
        "state": subgoal.state.value if isinstance(subgoal.state, SubgoalLifecycleState) else subgoal.state,
    }


def _subgoal_to_safe_dict(subgoal: Subgoal) -> Dict[str, Any]:
    """Convert a Subgoal to a JSON‑safe dict.

    Deep‑copies mutable fields to prevent external mutation.
    """
    return {
        "subgoal_id": subgoal.subgoal_id,
        "goal": subgoal.goal,
        "context": deepcopy(subgoal.context),
        "metadata": deepcopy(subgoal.metadata),
        "parent_id": subgoal.parent_id,
        "state": subgoal.state.value if isinstance(subgoal.state, SubgoalLifecycleState) else subgoal.state,
    }


def _get_segments_for_subgoal(
    subgoal: Subgoal,
    segments: Optional[List[PlanSegment]] = None,
) -> List[PlanSegment]:
    """Resolve segments associated with a subgoal.

    Parameters
    ----------
    subgoal
        The Subgoal to find segments for.
    segments
        Optional explicit list of PlanSegments.  If provided, filters to
        those whose ``subgoal_id`` matches this subgoal's id.

    Returns
    -------
    list[PlanSegment]
        Segments belonging to this subgoal (empty if none found).
    """
    if segments is not None:
        return [
            s for s in segments
            if s.subgoal_id == subgoal.subgoal_id
        ]
    # Fallback: look in subgoal.metadata for segment data
    meta_segments = subgoal.metadata.get("segments", [])
    if isinstance(meta_segments, list):
        return meta_segments
    return []


def _summarise_segment_status(segment: PlanSegment) -> Dict[str, Any]:
    """Produce a deterministic status summary for a single segment.

    A segment is "complete" when it has:
    - A non‑empty subgoal_id
    - At least one step
    - No malformed (None/non‑string) steps
    """
    has_id = bool(segment.subgoal_id and segment.subgoal_id.strip())
    has_steps = isinstance(segment.steps, list) and len(segment.steps) > 0
    malformed = 0
    if isinstance(segment.steps, list):
        for s in segment.steps:
            if s is None or not isinstance(s, str) or (isinstance(s, str) and not s.strip()):
                malformed += 1

    is_ok = has_id and has_steps and malformed == 0
    return {
        "segment_id": segment.segment_id,
        "complete": is_ok,
        "step_count": len(segment.steps) if isinstance(segment.steps, list) else 0,
        "malformed_steps": malformed,
    }


def _check_subgoal_for_drift(raw: Dict[str, Any]) -> List[UnifiedDriftSignal]:
    """Inspect a subgoal raw dict for structural malformations.

    Emits ``UnifiedDriftSignal`` instances for missing fields, type mismatches,
    and null/malformed values — deterministic, pure, JSON‑safe.

    Parameters
    ----------
    raw
        Raw dict representation of a Subgoal (from ``_subgoal_to_raw_dict``).

    Returns
    -------
    list[UnifiedDriftSignal]
        Structural drift signals, or an empty list if no issues are found.
    """
    signals: List[UnifiedDriftSignal] = []

    # ── subgoal_id ──
    sid = raw.get("subgoal_id")
    if not sid or not isinstance(sid, str) or not sid.strip():
        signals.append(
            UnifiedDriftSignal(
                source="structural",
                type="missing_field",
                weight=0.35,
                decay=1.0,
                confidence=0.7,
                details={"field": "subgoal_id", "issue": "missing_or_empty"},
            )
        )

    # ── goal ──
    goal = raw.get("goal")
    if not goal or not isinstance(goal, str) or not goal.strip():
        signals.append(
            UnifiedDriftSignal(
                source="structural",
                type="missing_field",
                weight=0.4,
                decay=1.0,
                confidence=0.75,
                details={"field": "goal", "issue": "missing_or_empty"},
            )
        )

    # ── context ──
    ctx = raw.get("context")
    if ctx is not None and not isinstance(ctx, dict):
        signals.append(
            UnifiedDriftSignal(
                source="structural",
                type="type_mismatch",
                weight=0.25,
                decay=1.0,
                confidence=0.5,
                details={
                    "field": "context",
                    "expected": "dict",
                    "got": type(ctx).__name__,
                },
            )
        )

    # ── metadata ──
    meta = raw.get("metadata")
    if meta is not None and not isinstance(meta, dict):
        signals.append(
            UnifiedDriftSignal(
                source="structural",
                type="type_mismatch",
                weight=0.25,
                decay=1.0,
                confidence=0.5,
                details={
                    "field": "metadata",
                    "expected": "dict",
                    "got": type(meta).__name__,
                },
            )
        )

    # ── state ──
    state_val = raw.get("state")
    if state_val and isinstance(state_val, str):
        valid_states = {s.value for s in SubgoalLifecycleState}
        if state_val not in valid_states:
            signals.append(
                UnifiedDriftSignal(
                    source="structural",
                    type="invalid_state",
                    weight=0.3,
                    decay=1.0,
                    confidence=0.6,
                    details={"field": "state", "value": state_val, "valid": sorted(valid_states)},
                )
            )

    return signals


# ──────────────────────────────────────────────────────────────────────────────
# Public reflection functions
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_subgoal_progress(
    subgoal: Subgoal,
    segments: Optional[List[PlanSegment]] = None,
) -> dict:
    """Produce a deterministic structural summary of a subgoal.

    Returns
    -------
    dict
        Keys:
        - ``segment_count`` (int) — number of segments associated with this subgoal.
        - ``completed_segments`` (int) — number of segments that are structurally complete.
        - ``missing_fields`` (list[str], optional) — required fields that are
          missing, empty, or of the wrong type.
        - ``malformed_segments`` (int, optional) — count of segments with malformed steps.
    """
    raw = _subgoal_to_raw_dict(subgoal)
    missing: List[str] = []

    # Check subgoal_id
    sid = raw.get("subgoal_id")
    if not sid or not isinstance(sid, str) or not sid.strip():
        missing.append("subgoal_id")

    # Check goal
    goal = raw.get("goal")
    if not goal or not isinstance(goal, str) or not goal.strip():
        missing.append("goal")

    # Check context
    ctx = raw.get("context")
    if ctx is not None and not isinstance(ctx, dict):
        missing.append("context")

    # Check metadata
    meta = raw.get("metadata")
    if meta is not None and not isinstance(meta, dict):
        missing.append("metadata")

    # Segment analysis
    associated = _get_segments_for_subgoal(subgoal, segments)
    segment_count = len(associated)
    completed = 0
    malformed_segments = 0

    for seg in associated:
        summary = _summarise_segment_status(seg)
        if summary["complete"]:
            completed += 1
        if summary["malformed_steps"] > 0:
            malformed_segments += 1

    result: Dict[str, Any] = {"segment_count": segment_count, "completed_segments": completed}
    if missing:
        result["missing_fields"] = sorted(missing)  # deterministic ordering
    if malformed_segments > 0:
        result["malformed_segments"] = malformed_segments
    return result


def evaluate_subgoal_drift(
    subgoal: Subgoal,
    segments: Optional[List[PlanSegment]] = None,
) -> dict:
    """Detect drift in a subgoal using the existing drift classifier.

    Converts the subgoal to a raw dict, generates structural drift signals
    (including segment-level drift for associated segments), and classifies
    them via ``classify_unified_drift``.

    Returns
    -------
    dict
        Keys: ``status``, ``severity``, ``categories``, ``confidence``,
        ``streak``, ``signal_count``.
    """
    raw = _subgoal_to_raw_dict(subgoal)
    signals = _check_subgoal_for_drift(raw)

    # Also check associated segments for drift
    associated = _get_segments_for_subgoal(subgoal, segments)
    for seg in associated:
        seg_summary = _summarise_segment_status(seg)
        if not seg_summary["complete"]:
            if seg_summary["malformed_steps"] > 0:
                signals.append(
                    UnifiedDriftSignal(
                        source="structural",
                        type="malformed_segment",
                        weight=0.3,
                        decay=1.0,
                        confidence=0.6,
                        details={
                            "segment_id": seg.segment_id,
                            "malformed_steps": seg_summary["malformed_steps"],
                        },
                    )
                )
            if seg_summary["step_count"] == 0:
                signals.append(
                    UnifiedDriftSignal(
                        source="structural",
                        type="empty_segment",
                        weight=0.25,
                        decay=1.0,
                        confidence=0.5,
                        details={
                            "segment_id": seg.segment_id,
                            "issue": "no_steps",
                        },
                    )
                )

    classification = classify_unified_drift(signals)
    return {
        "status": classification.status,
        "severity": classification.severity,
        "categories": list(classification.categories),
        "confidence": classification.confidence,
        "streak": classification.streak,
        "signal_count": len(signals),
    }


def evaluate_subgoal_repair(
    subgoal: Subgoal,
    drift: dict,
    segments: Optional[List[PlanSegment]] = None,
) -> dict:
    """Apply repair to a subgoal if drift is detected.

    Reuses ``repair_subgoal`` from the existing repair action library.

    Parameters
    ----------
    subgoal
        The Subgoal to evaluate.
    drift
        Drift dict produced by ``evaluate_subgoal_drift``.
    segments
        Optional associated PlanSegments.

    Returns
    -------
    dict
        ``{"action": "none", "repaired": <subgoal_dict>}`` when no drift.
        ``{"action": "repair_subgoal", "repaired": <subgoal_dict>}`` on success.
        ``{"action": "repair_failed", "reason": ..., "repaired": ...}`` on failure.
    """
    if drift.get("status") == "no_drift":
        return {"action": "none", "repaired": _subgoal_to_safe_dict(subgoal)}

    try:
        repaired = repair_subgoal(subgoal)
        return {"action": "repair_subgoal", "repaired": _subgoal_to_safe_dict(repaired)}
    except Exception as exc:
        return {
            "action": "repair_failed",
            "reason": str(exc),
            "repaired": _subgoal_to_safe_dict(subgoal),
        }


def evaluate_subgoal_completion(
    subgoal: Subgoal,
    segments: Optional[List[PlanSegment]] = None,
) -> bool:
    """Determine whether a subgoal is complete.

    A subgoal is complete when:
    - All required fields are present (no ``missing_fields`` in progress).
    - All associated segments are complete.
    - No drift requiring repair is detected.

    Returns
    -------
    bool
        ``True`` if the subgoal is complete, ``False`` otherwise.
    """
    progress = evaluate_subgoal_progress(subgoal, segments)
    if progress.get("missing_fields"):
        return False
    if progress.get("malformed_segments", 0) > 0:
        return False

    drift = evaluate_subgoal_drift(subgoal, segments)
    if drift.get("status") != "no_drift":
        return False
    return True


def reflect_on_subgoal(
    subgoal: Subgoal,
    segments: Optional[List[PlanSegment]] = None,
) -> SubgoalReflectionResult:
    """Run the full subgoal reflection pipeline.

    Executes in deterministic order:
    1. progress evaluation
    2. drift evaluation
    3. repair evaluation
    4. completion evaluation

    Parameters
    ----------
    subgoal
        The Subgoal to reflect on.
    segments
        Optional list of PlanSegments to use for segment-aware progress
        and drift evaluation.  If omitted, falls back to subgoal.metadata.

    Returns
    -------
    SubgoalReflectionResult
        Frozen result with progress, drift, repair, and is_complete fields.
    """
    progress = evaluate_subgoal_progress(subgoal, segments)
    drift = evaluate_subgoal_drift(subgoal, segments)
    repair = evaluate_subgoal_repair(subgoal, drift, segments)
    is_complete = evaluate_subgoal_completion(subgoal, segments)

    return SubgoalReflectionResult(
        progress=progress,
        drift=drift,
        repair=repair,
        is_complete=is_complete,
    )

"""
Phase 2.11.2 — Segment Reflection
==================================

Deterministic, pure‑function reflection logic for segment‑level execution.

Reflection evaluates:
- segment progress (structural summary)
- segment drift (reuses existing drift classifier)
- segment repair (reuses existing repair engine)
- segment completion (boolean predicate)

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

from dataclasses import dataclass
from typing import Any, Dict, List

from src.strategy.planning.drift.repair_action_library import repair_segment
from src.strategy.planning.drift.unified_drift_classifier import classify_unified_drift
from src.strategy.planning.drift.unified_drift_types import (
    UnifiedDriftClassification,
    UnifiedDriftSignal,
)
from src.strategy.types.plan_segment import PlanSegment


# ──────────────────────────────────────────────────────────────────────────────
# SegmentReflectionResult
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SegmentReflectionResult:
    """Deterministic reflection result for a single segment.

    Fields
    ------
    progress
        Structural summary dict with ``step_count``, ``missing_fields``,
        and ``malformed_steps`` keys.
    drift
        Dict snapshot of the ``UnifiedDriftClassification`` produced by
        running the existing drift classifier on the segment.
    repair
        Dict with ``action`` (``"none"``, ``"repair_segment"``, or
        ``"repair_failed"``) and ``repaired`` (the segment dict after repair).
    is_complete
        ``True`` when the segment has no missing fields, no malformed steps,
        and no drift requiring repair.
    """
    progress: dict
    drift: dict
    repair: dict
    is_complete: bool


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _segment_to_raw_dict(segment: PlanSegment) -> Dict[str, Any]:
    """Convert a PlanSegment to a raw dict for structural inspection.

    Never mutates the input — returns a fresh dict.
    """
    return {
        "subgoal_id": segment.subgoal_id,
        "steps": list(segment.steps),
        "context": segment.context,
        "metadata": segment.metadata,
    }


def _segment_to_safe_dict(segment: PlanSegment) -> Dict[str, Any]:
    """Convert a PlanSegment to a JSON‑safe dict.

    Deep‑copies mutable fields to prevent external mutation.
    """
    from copy import deepcopy

    return {
        "subgoal_id": segment.subgoal_id,
        "steps": list(segment.steps),
        "context": deepcopy(segment.context),
        "metadata": deepcopy(segment.metadata),
    }


def _check_segment_for_drift(raw: Dict[str, Any]) -> List[UnifiedDriftSignal]:
    """Inspect a segment raw dict for structural malformations.

    Emits ``UnifiedDriftSignal`` instances for missing fields, type mismatches,
    and null/malformed steps — deterministic, pure, JSON‑safe.

    Parameters
    ----------
    raw
        Raw dict representation of a PlanSegment (from ``_segment_to_raw_dict``).

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

    # ── steps ──
    steps = raw.get("steps")
    if not isinstance(steps, list):
        signals.append(
            UnifiedDriftSignal(
                source="structural",
                type="type_mismatch",
                weight=0.35,
                decay=1.0,
                confidence=0.7,
                details={
                    "field": "steps",
                    "expected": "list",
                    "got": type(steps).__name__,
                },
            )
        )
    elif len(steps) == 0:
        signals.append(
            UnifiedDriftSignal(
                source="structural",
                type="empty_steps",
                weight=0.35,
                decay=1.0,
                confidence=0.7,
                details={"field": "steps", "issue": "empty"},
            )
        )
    else:
        for i, s in enumerate(steps):
            if s is None:
                signals.append(
                    UnifiedDriftSignal(
                        source="structural",
                        type="null_step",
                        weight=0.3,
                        decay=1.0,
                        confidence=0.6,
                        details={"step_index": i, "issue": "null"},
                    )
                )
            elif not isinstance(s, str):
                signals.append(
                    UnifiedDriftSignal(
                        source="structural",
                        type="type_mismatch",
                        weight=0.3,
                        decay=1.0,
                        confidence=0.6,
                        details={
                            "step_index": i,
                            "expected": "str",
                            "got": type(s).__name__,
                        },
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

    return signals


# ──────────────────────────────────────────────────────────────────────────────
# Public reflection functions
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_segment_progress(segment: PlanSegment) -> dict:
    """Produce a deterministic structural summary of a segment.

    Returns
    -------
    dict
        Keys:
        - ``step_count`` (int) — number of steps in the segment.
        - ``missing_fields`` (list[str], optional) — required fields that are
          missing, empty, or of the wrong type.
        - ``malformed_steps`` (int, optional) — count of steps that are None
          or non‑string.
    """
    raw = _segment_to_raw_dict(segment)
    missing: List[str] = []
    malformed = 0

    # Check subgoal_id
    sid = raw.get("subgoal_id")
    if not sid or not isinstance(sid, str) or not sid.strip():
        missing.append("subgoal_id")

    # Check steps
    steps = raw.get("steps")
    step_count: int
    if isinstance(steps, list):
        step_count = len(steps)
        for s in steps:
            if s is None or not isinstance(s, str) or (isinstance(s, str) and not s.strip()):
                malformed += 1
        if step_count == 0:
            if "steps" not in missing:
                missing.append("steps")
    else:
        step_count = 0
        missing.append("steps")

    # Check context (metadata is optional)
    ctx = raw.get("context")
    if ctx is not None and not isinstance(ctx, dict):
        missing.append("context")

    result: Dict[str, Any] = {"step_count": step_count}
    if missing:
        result["missing_fields"] = sorted(missing)  # deterministic ordering
    if malformed > 0:
        result["malformed_steps"] = malformed
    return result


def evaluate_segment_drift(segment: PlanSegment) -> dict:
    """Detect drift in a segment using the existing drift classifier.

    Converts the segment to a raw dict, generates structural drift signals,
    and classifies them via ``classify_unified_drift``.

    Returns
    -------
    dict
        Keys: ``status``, ``severity``, ``categories``, ``confidence``,
        ``streak``, ``signal_count``.
    """
    raw = _segment_to_raw_dict(segment)
    signals = _check_segment_for_drift(raw)
    classification = classify_unified_drift(signals)
    return {
        "status": classification.status,
        "severity": classification.severity,
        "categories": list(classification.categories),
        "confidence": classification.confidence,
        "streak": classification.streak,
        "signal_count": len(signals),
    }


def evaluate_segment_repair(segment: PlanSegment, drift: dict) -> dict:
    """Apply repair to a segment if drift is detected.

    Reuses ``repair_segment`` from the existing repair action library.

    Parameters
    ----------
    segment
        The PlanSegment to evaluate.
    drift
        Drift dict produced by ``evaluate_segment_drift``.

    Returns
    -------
    dict
        ``{"action": "none", "repaired": <segment_dict>}`` when no drift.
        ``{"action": "repair_segment", "repaired": <segment_dict>}`` on success.
        ``{"action": "repair_failed", "reason": ..., "repaired": ...}`` on failure.
    """
    if drift.get("status") == "no_drift":
        return {"action": "none", "repaired": _segment_to_safe_dict(segment)}

    try:
        repaired = repair_segment(segment)
        return {"action": "repair_segment", "repaired": _segment_to_safe_dict(repaired)}
    except Exception as exc:
        return {
            "action": "repair_failed",
            "reason": str(exc),
            "repaired": _segment_to_safe_dict(segment),
        }


def evaluate_segment_completion(segment: PlanSegment) -> bool:
    """Determine whether a segment is complete.

    A segment is complete when:
    - All required fields are present (no ``missing_fields`` in progress).
    - No steps are malformed.
    - No drift requiring repair is detected.

    Returns
    -------
    bool
        ``True`` if the segment is complete, ``False`` otherwise.
    """
    progress = evaluate_segment_progress(segment)
    if progress.get("missing_fields"):
        return False
    if progress.get("malformed_steps", 0) > 0:
        return False

    drift = evaluate_segment_drift(segment)
    if drift.get("status") != "no_drift":
        return False
    return True


def reflect_on_segment(segment: PlanSegment) -> SegmentReflectionResult:
    """Run the full segment reflection pipeline.

    Executes in deterministic order:
    1. progress evaluation
    2. drift evaluation
    3. repair evaluation
    4. completion evaluation

    Parameters
    ----------
    segment
        The PlanSegment to reflect on.

    Returns
    -------
    SegmentReflectionResult
        Frozen result with progress, drift, repair, and is_complete fields.
    """
    progress = evaluate_segment_progress(segment)
    drift = evaluate_segment_drift(segment)
    repair = evaluate_segment_repair(segment, drift)
    is_complete = evaluate_segment_completion(segment)

    return SegmentReflectionResult(
        progress=progress,
        drift=drift,
        repair=repair,
        is_complete=is_complete,
    )

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

from src.strategy.memory.segment_memory_types import SegmentMemoryRecord
from src.strategy.planning.drift.behavioural_signal_types import (
    BehaviouralSignal,
    BehaviouralSignalType,
)
from src.strategy.planning.validation.execution_shape_validation import (
    validate_execution_shape,
)

# Sentinel to distinguish "key absent" from "value is None"
_MISSING: object = object()


def _iso_from_ms(ts_ms: int) -> str:
    """Convert a millisecond timestamp to an ISO 8601 string (UTC)."""
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Individual signal detectors (one per BehaviouralSignalType)
# ---------------------------------------------------------------------------


def detect_wrong_capability(
    record: SegmentMemoryRecord,
    ts_ms: int,
) -> Optional[BehaviouralSignal]:
    """
    Detect when the segment's declared capability does not match the
    capability actually executed.

    Compares ``record.metadata["declared_capability"]`` against
    ``record.metadata["executed_capability"]``.

    Returns None when:
      - Either key is absent from metadata
      - Both values match (including None)
      - Values are equal strings
    """
    declared = record.metadata.get("declared_capability")
    executed = record.metadata.get("executed_capability")

    # No data to compare — nothing to signal
    if declared is None or executed is None:
        return None

    # Normalise to strings for deterministic comparison
    declared_str = str(declared)
    executed_str = str(executed)

    if declared_str == executed_str:
        return None

    return BehaviouralSignal(
        signal_type=BehaviouralSignalType.WRONG_CAPABILITY,
        segment_id=record.segment_id,
        subgoal_id=record.subgoal_id,
        details={
            "declared_capability": declared_str,
            "executed_capability": executed_str,
        },
        timestamp=_iso_from_ms(ts_ms),
    )


def detect_wrong_output_shape(
    record: SegmentMemoryRecord,
    ts_ms: int,
) -> Optional[BehaviouralSignal]:
    """
    Detect when the actual executor output shape does not conform to the
    declared output schema.

    Uses the existing ``validate_execution_shape()`` to compare
    ``record.metadata["declared_output_schema"]`` against
    ``record.last_output``.

    Returns None when:
      - ``declared_output_schema`` is absent from metadata
      - ``last_output`` is None (nothing to validate)
      - Structural validation succeeds
    """
    declared_schema = record.metadata.get("declared_output_schema")
    actual = record.last_output

    if declared_schema is None or actual is None:
        return None

    result = validate_execution_shape(declared_schema, actual)
    if result.ok:
        return None

    return BehaviouralSignal(
        signal_type=BehaviouralSignalType.WRONG_OUTPUT_SHAPE,
        segment_id=record.segment_id,
        subgoal_id=record.subgoal_id,
        details={
            "declared_output_schema": declared_schema,
            "actual_type": type(actual).__name__,
            "validation_message": result.message,
        },
        timestamp=_iso_from_ms(ts_ms),
    )


def detect_wrong_output_semantics(
    record: SegmentMemoryRecord,
    ts_ms: int,
) -> Optional[BehaviouralSignal]:
    """
    Detect when output is structurally valid but violates simple behavioural
    expectations.

    Heuristics applied (deterministic, no LLM):
      1. If output is a dict and ``"success"`` is ``False`` → signal.
      2. If output is a dict and ``"ok"`` is ``False`` → signal.
      3. If output is a dict and ``"error"`` is a non-empty value → signal.
      4. If the declared output schema lists required fields, and any of
         them is present but empty (``None``, ``""``, ``[]``, ``{}``) → signal.

    Returns None when:
      - ``last_output`` is None (nothing to inspect)
      - None of the heuristics trigger
    """
    actual = record.last_output
    if actual is None:
        return None

    reasons: List[str] = []

    if isinstance(actual, dict):
        # ── success flag is false ──────────────────────────────────────
        success = actual.get("success", _MISSING)
        if success is not _MISSING and success is False:
            reasons.append("success_flag_false")

        # ── ok flag is false ───────────────────────────────────────────
        ok = actual.get("ok", _MISSING)
        if ok is not _MISSING and ok is False:
            reasons.append("ok_flag_false")

        # ── error field is non-empty ───────────────────────────────────
        error = actual.get("error", _MISSING)
        if error is not _MISSING and error is not None and error != "" and error != [] and error != {}:
            reasons.append("error_field_populated")

        # ── required fields present but empty ──────────────────────────
        declared_schema = record.metadata.get("declared_output_schema")
        if isinstance(declared_schema, dict):
            required: List[str] = declared_schema.get("required", [])
            for field in required:
                val = actual.get(field, _MISSING)
                if val is not _MISSING and _is_empty_value(val):
                    reasons.append(f"required_field_empty:{field}")

    if not reasons:
        return None

    return BehaviouralSignal(
        signal_type=BehaviouralSignalType.WRONG_OUTPUT_SEMANTICS,
        segment_id=record.segment_id,
        subgoal_id=record.subgoal_id,
        details={
            "reasons": reasons,
            "actual_type": type(actual).__name__,
        },
        timestamp=_iso_from_ms(ts_ms),
    )


def _is_empty_value(val: object) -> bool:
    """Return True if *val* is a semantically empty value."""
    return val is None or val == "" or val == [] or val == {}


def _declares_no_side_effects(declared: object) -> bool:
    """Return True if *declared* represents "no side effects"."""
    if declared is None:
        return True
    if isinstance(declared, str):
        return declared.lower() in ("none", "")
    if isinstance(declared, (list, tuple)):
        return len(declared) == 0
    # Any other truthy value means side effects are declared
    return False


def _has_side_effects(executed: object) -> bool:
    """Return True if *executed* reports at least one side effect."""
    if executed is None:
        return False
    if isinstance(executed, str):
        return executed.lower() not in ("none", "")
    if isinstance(executed, (list, tuple)):
        return len(executed) > 0
    if isinstance(executed, dict):
        return len(executed) > 0
    # Unknown type — conservatively assume side effects
    return bool(executed)


def detect_unexpected_side_effect(
    record: SegmentMemoryRecord,
    ts_ms: int,
) -> Optional[BehaviouralSignal]:
    """
    Detect when a primitive declared no side effects but actually produced them.

    Reads ``record.metadata["declared_side_effects"]`` and
    ``record.metadata["executed_side_effects"]``.  Emits UNEXPECTED_SIDE_EFFECT
    when the declared value represents "no side effects" (``None``, ``"none"``,
    ``""``, or an empty list) but the executed value reports at least one.

    Returns None when:
      - At least one of the keys is missing from metadata
      - The declared value already allows side effects
      - The executed value is empty / reports no side effects
    """
    declared = record.metadata.get("declared_side_effects", _MISSING)
    executed = record.metadata.get("executed_side_effects", _MISSING)

    # Both keys must be present
    if declared is _MISSING or executed is _MISSING:
        return None

    # Only signal when declared says "none" but execution says otherwise
    if not _declares_no_side_effects(declared):
        return None

    if not _has_side_effects(executed):
        return None

    return BehaviouralSignal(
        signal_type=BehaviouralSignalType.UNEXPECTED_SIDE_EFFECT,
        segment_id=record.segment_id,
        subgoal_id=record.subgoal_id,
        details={
            "declared_side_effects": declared,
            "executed_side_effects": executed,
        },
        timestamp=_iso_from_ms(ts_ms),
    )


# ---------------------------------------------------------------------------
# Collector — runs all 2.6.3 detectors against a collection of records
# ---------------------------------------------------------------------------


def collect_behavioural_drift_signals(
    records: Sequence[SegmentMemoryRecord],
    ts_ms: int,
) -> Dict[str, List[BehaviouralSignal]]:
    """
    Run all Phase 2.6.3 behavioural drift detectors against the given
    segment records.

    Returns a mapping of ``segment_id`` → list of detected signals.
    Segments with no signals are omitted from the result.

    All detectors are pure and deterministic — no side effects.
    """
    result: Dict[str, List[BehaviouralSignal]] = {}

    for record in records:
        signals: List[BehaviouralSignal] = []

        # ── WRONG_CAPABILITY ──────────────────────────────────────────
        cap_signal = detect_wrong_capability(record, ts_ms)
        if cap_signal is not None:
            signals.append(cap_signal)

        # ── WRONG_OUTPUT_SHAPE ──────────────────────────────────────────
        shape_signal = detect_wrong_output_shape(record, ts_ms)
        if shape_signal is not None:
            signals.append(shape_signal)

        # ── WRONG_OUTPUT_SEMANTICS ─────────────────────────────────────
        sem_signal = detect_wrong_output_semantics(record, ts_ms)
        if sem_signal is not None:
            signals.append(sem_signal)

        # ── UNEXPECTED_SIDE_EFFECT ────────────────────────────────────
        se_signal = detect_unexpected_side_effect(record, ts_ms)
        if se_signal is not None:
            signals.append(se_signal)

        if signals:
            result[record.segment_id] = signals

    return result

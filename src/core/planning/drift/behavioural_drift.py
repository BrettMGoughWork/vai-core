from __future__ import annotations

from typing import Any, Dict, Optional

from src.core.memory.drift_memory import DriftMemory
from src.core.memory.drift_memory_types import DriftEvent
from src.core.signals.model import (
    SignalType,
    SignalSeverity,
    GovernedSignal,
)
from src.core.planning.validation.execution_shape_validation import (
    ShapeValidationResult,
    validate_execution_shape,
)

def evaluate_behavioural_drift(
    *,
    drift_memory: DriftMemory,
    subgoal_id: str,
    segment_id: str,
    step_id: str,
    expected_schema: Optional[Dict[str, Any]],
    actual_output: Any,
) -> Optional[GovernedSignal]:
    """
    2.6.1 — Compare expected vs actual executor output and emit a behavioural drift signal if needed.
    """
    shape_result: ShapeValidationResult = validate_execution_shape(
        expected_schema=expected_schema,
        actual_output=actual_output,
    )

    if shape_result.ok:
        return None

    signal_type = SignalType.BEHAVIOURAL_SHAPE_MISMATCH

    signal = GovernedSignal(
        signal_type=signal_type,
        severity=SignalSeverity.WARNING,
        message="Executor output does not match expected capability shape.",
        details={
            "subgoal_id": subgoal_id,
            "segment_id": segment_id,
            "step_id": step_id,
            "validation_message": shape_result.message,
            "validation_details": shape_result.details or {},
        },
    )

    # Record into DriftMemory for later multi‑cycle reasoning.
    event = DriftEvent(
        timestamp=None, # let DriftEvent default or set inside constructor if needed
        subgoal_id=subgoal_id,
        segment_id=segment_id,
        step_id=step_id,
        signal_type=signal.signal_type.name,
        confidence=0.7, # initial heuristic; refined in later phases
        details=signal.details or {},
    )
    drift_memory.record(event)

    return signal
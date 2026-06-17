"""R.11.7 — Post-execution Validation Pipeline.

Orchestrates shape validation, behavioural anomaly detection, and
drift evaluation after skill execution.  Lives in the utility stratum
so it can legally import strategy-layer drift and validation helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from src.strategy.memory.drift_memory import DriftMemory
from src.strategy.planning.drift.behavioural_drift import evaluate_behavioural_drift
from src.strategy.planning.validation.execution_shape_validation import (
    detect_behavioural_anomaly,
    validate_execution_shape,
)
from src.strategy.signals.model import GovernedSignal


@dataclass
class ValidationDiagnostics:
    """Diagnostic output from a single validation-pipeline run."""

    shape_ok: bool = True
    shape_message: str = ""
    anomaly: Optional[str] = None
    drift_signal: Optional[GovernedSignal] = None


class ValidationPipeline:
    """Post-execution validation pipeline.

    Holds a ``DriftMemory`` ring buffer and provides an ``apply`` method
    that runs shape validation -> anomaly detection -> drift evaluation.

    When ``expected_schema`` is ``None`` the pipeline is a graceful no-op
    (shape validation already returns ``ok=True`` in that case).
    """

    def __init__(self, drift_memory: DriftMemory | None = None) -> None:
        self._drift_memory = drift_memory if drift_memory is not None else DriftMemory()

    @property
    def drift_memory(self) -> DriftMemory:
        """Expose the internal DriftMemory for inspection in tests."""
        return self._drift_memory

    def apply(
        self,
        *,
        skill_name: str,
        actual_output: Any,
        expected_schema: Optional[Dict[str, Any]] = None,
        subgoal_id: str = "",
        segment_id: str = "",
        step_id: str = "",
    ) -> ValidationDiagnostics:
        """Run the full validation pipeline for a single skill execution.

        Parameters
        ----------
        skill_name:
            Name of the executed skill (included in diagnostics).
        actual_output:
            The output produced by the skill.
        expected_schema:
            Optional JSON-schema-like dict describing the expected output
            shape.  When ``None`` the pipeline is a graceful no-op.
        subgoal_id, segment_id, step_id:
            Identifiers for drift-event recording.

        Returns
        -------
        ValidationDiagnostics with the results of each stage.
        """
        diagnostics = ValidationDiagnostics()

        # 1. Shape validation
        shape_result = validate_execution_shape(
            expected_schema=expected_schema,
            actual_output=actual_output,
        )
        diagnostics.shape_ok = shape_result.ok
        diagnostics.shape_message = shape_result.message

        # 2. Behavioural anomaly detection (lightweight heuristic)
        diagnostics.anomaly = detect_behavioural_anomaly(
            expected_schema=expected_schema,
            actual_output=actual_output,
        )

        # 3. Drift evaluation — requires subgoal_id for event recording
        if subgoal_id:
            diagnostics.drift_signal = evaluate_behavioural_drift(
                drift_memory=self._drift_memory,
                subgoal_id=subgoal_id,
                segment_id=segment_id,
                step_id=step_id,
                expected_schema=expected_schema,
                actual_output=actual_output,
            )

        return diagnostics

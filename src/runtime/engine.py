from __future__ import annotations

from typing import Any, Dict

from src.capabilities.primitives.base import PrimitiveBase
from src.runtime.errors import ToolExecutionError
from src.strategy.types.result import CoreResult
from src.strategy.planning.validation.execution_shape_validation import validate_execution_shape
from src.strategy.memory.drift_memory import DriftMemory
from src.strategy.planning.drift.behavioural_drift import evaluate_behavioural_drift
from src.strategy.planning.validation.behavioural_anomaly import detect_behavioural_anomaly

def execute_tool(
        skill: BaseSkill, 
        args: Dict[str, Any], 
        *,
        drift_memory: DriftMemory,
        subgoal_id: str,
        segment_id: str,
        step_id: str
        ) -> CoreResult:
    """
    Execute a skill with full validation + canonicalisation pipeline.
    This is the single entrypoint for tool execution.
    """

    try:
        # Execute capability (S1) ---
        output = skill.run(**args)

        # --- 2.6.1 execution shape + behavioural drift observation ---
        expected_schema = getattr(skill, "output_schema", None)
        
        # -- Execution-shape validation (S1) ---
        shape_result = validate_execution_shape(
            expected_schema=expected_schema,
            actual_output=output,
        )

        anomaly = detect_behavioural_anomaly(expected_schema, output)

        if anomaly is not None:
            evaluate_behavioural_drift(
                drift_memory=drift_memory,
                subgoal_id=subgoal_id,
                segment_id=segment_id,
                step_id=step_id,
                expected_schema=expected_schema,
                actual_output=output,
            )

        # --- Behavioural drift emission (S1) ---
        if not shape_result.ok:
            evaluate_behavioural_drift(
                drift_memory=drift_memory,
                subgoal_id=subgoal_id,
                segment_id=segment_id,
                step_id=step_id,
                expected_schema=expected_schema,
                actual_output=output,
            )

        return CoreResult.from_tool(skill.name, output)

    except Exception as e:
        return CoreResult.from_error(
            ToolExecutionError(f"Tool '{skill.name}' failed: {e}")
        )

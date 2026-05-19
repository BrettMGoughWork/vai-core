from dataclasses import dataclass
from core.planning.step_state import StepState
from core.planning.step_result import StepResult
from core.planning.step_result_factory import (
    success,
    failure,
    tool_needed,
    continue_reasoning,
)


@dataclass(frozen=True)
class DefaultOutcomeClassifier:
    """
    A placeholder deterministic classifier.
    Replace with real logic in PHASE 2.1.5.
    """

    def classify(self, state: StepState) -> StepResult:
        # Example deterministic rule:
        # If cognitive_input contains "tool", request tool execution.
        ci = state.cognitive_input

        if "tool" in ci:
            return tool_needed(
                reason="Tool requested by cognitive input",
                payload={"tool": ci["tool"]},
            )

        # If cognitive_input contains "error", fail deterministically.
        if "error" in ci:
            return failure(
                reason="Cognitive input indicates error",
                payload={"detail": ci["error"]},
            )

        # Default: continue reasoning
        return continue_reasoning(
            reason="No tool or error detected; continue reasoning",
            payload={},
        )
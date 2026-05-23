from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .outcome_classifier import OutcomeClassifier
from src.core.planning.step_state import StepState, StepStatus
from src.core.planning.step_result import StepOutcome, StepResult
from src.core.types.hashing import stable_hash
from src.core.planning.cognitive_contract import validate_cognitive_input

@dataclass(frozen=True)
class CoreStepV2:
    """
    Pure cognitive step executor (Stratum 2).
    """
    classifier: OutcomeClassifier = OutcomeClassifier()

    def run(self, state: StepState) -> Tuple[StepState, StepResult]:
        # 1. Validate input purity
        validate_cognitive_input(
            state=state,
            last_result=state.last_result,
            memory_snapshot=state.cognitive_input.get("memory", {}),
        )

        # 2. Transition → RUNNING
        running_state = self._to_running(state)

        # 3. Classify outcome (pure)
        result = self._classify(running_state)

        # 4. Transition → DONE / ERROR based on outcome
        final_state = self._apply_outcome(running_state, result)

        # 5. Append trace
        final_state = self._append_trace(final_state, result)

        # 6. Return new_state, result
        return final_state, result

    # --- Internal helpers (pure, deterministic) ---
    def _to_running(self, state: StepState) -> StepState:
        # You’ll likely implement a replace() helper on StepState;
        # for now assume a simple constructor pattern.
        return state.replace(status=StepStatus.RUNNING)

    def _classify(self, state: StepState) -> StepResult:
        raw = state.cognitive_input["raw_classifier_output"]
        return self.classifier.classify(state, raw)

    def _apply_outcome(self, state: StepState, result: StepResult) -> StepState:
        # For now, keep it simple: DONE on success/continue/tool, ERROR on failure.
        if result.outcome == StepOutcome.FAILURE:
            new_status = StepStatus.ERROR
        else:
            new_status = StepStatus.DONE

        return state.replace(status=new_status)

    def _append_trace(self, state: StepState, result: StepResult) -> StepState:
        # Minimal trace: record canonical hash + outcome
        new_trace = state.trace + [{
            "core_step_v2": {
                "hash": stable_hash({
                    "step_id": state.step_id,
                    "cognitive_input": state.cognitive_input,
                    "last_result": state.last_result,
                }),
                "outcome": result.outcome.value,
            }
        }]

        return state.replace(trace=new_trace)

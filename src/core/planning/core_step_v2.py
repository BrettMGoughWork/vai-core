from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple

from src.core.planning.step_state import StepState, StepStatus
from src.core.planning.step_result import StepOutcome, StepResult
from src.core.planning.step_result_factory import (
    success,
    failure,
    tool_needed,
    continue_reasoning,
)
from core.types.validation import validate_pure_structure
from core.types.errors import ValidationError
from core.types.hashing import stable_hash

# You’ll define this interface separately in outcome_classifier.py
class OutcomeClassifier:
    def classify(self, state: StepState) -> StepResult:
        """
        Pure classification of a StepState into a StepResult.
        No LLM calls, no tools, no side effects.
        """
        raise NotImplementedError


@dataclass(frozen=True)
class CoreStepV2:
    """
    Pure cognitive step executor (Stratum 2).

    Responsibilities:
    - Validate StepState
    - Transition lifecycle (PENDING → RUNNING → DONE/ERROR)
    - Call OutcomeClassifier
    - Produce StepResult
    - Append cognitive trace
    - Return new StepState + StepResult
    """

    classifier: OutcomeClassifier

    def run(self, state: StepState) -> Tuple[StepState, StepResult]:
        # 1. Validate input purity
        self._validate_state(state)

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

    def _validate_state(self, state: StepState) -> None:
        # StepState should already be pure, but we double‑check
        try:
            validate_pure_structure(state.cognitive_input)
            validate_pure_structure(state.last_result)
            validate_pure_structure(state.trace)
        except Exception as e:
            raise ValidationError(f"Invalid StepState for CoreStepV2: {e}")

    def _to_running(self, state: StepState) -> StepState:
        # You’ll likely implement a replace() helper on StepState;
        # for now assume a simple constructor pattern.
        return StepState(
            step_id=state.step_id,
            parent_id=state.parent_id,
            cognitive_input=state.cognitive_input,
            last_result=state.last_result,
            status=StepStatus.RUNNING,
            created_at=state.created_at,
            attempt=state.attempt,
            trace=state.trace,
            canonical_hash=state.canonical_hash,
        )

    def _classify(self, state: StepState) -> StepResult:
        # Delegates to a pure classifier (no LLM, no tools)
        result = self.classifier.classify(state)
        # Defensive purity check
        validate_pure_structure(result.payload)
        validate_pure_structure(result.trace)
        return result

    def _apply_outcome(self, state: StepState, result: StepResult) -> StepState:
        # For now, keep it simple: DONE on success/continue/tool, ERROR on failure.
        if result.outcome == StepOutcome.FAILURE:
            new_status = StepStatus.ERROR
        else:
            new_status = StepStatus.DONE

        return StepState(
            step_id=state.step_id,
            parent_id=state.parent_id,
            cognitive_input=state.cognitive_input,
            last_result={"outcome": result.outcome.value, "payload": result.payload},
            status=new_status,
            created_at=state.created_at,
            attempt=state.attempt,
            trace=state.trace,
            canonical_hash=state.canonical_hash,
        )

    def _append_trace(self, state: StepState, result: StepResult) -> StepState:
        # Minimal trace: record canonical hash + outcome
        new_trace = {
            **state.trace,
            "core_step_v2": {
                "hash": stable_hash(
                    {
                        "step_id": state.step_id,
                        "cognitive_input": state.cognitive_input,
                        "last_result": state.last_result,
                    }
                ),
                "outcome": result.outcome.value,
            },
        }

        return StepState(
            step_id=state.step_id,
            parent_id=state.parent_id,
            cognitive_input=state.cognitive_input,
            last_result=state.last_result,
            status=state.status,
            created_at=state.created_at,
            attempt=state.attempt,
            trace=new_trace,
            canonical_hash=state.canonical_hash,
        )
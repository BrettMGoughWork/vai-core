from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from src.core.planning.cognitive_normaliser import normalise_cognitive_structure

from .outcome_classifier import OutcomeClassifier
from src.core.planning.step_state import StepState, StepStatus
from src.core.planning.step_result import StepOutcome, StepResult
from src.core.types.hashing import stable_hash
from src.core.planning.cognitive_contract import validate_cognitive_input
from src.core.planning.trace_event import TraceEventBuilder
from src.core.planning.purity_enforcer import enforce_cognitive_purity

# In practice, you’d inject this or construct it at a higher level.
TRACE_BUILDER = TraceEventBuilder()

@dataclass(frozen=True)
class CoreStepV2:
    """
    Pure cognitive step executor (Stratum 2).
    """
    classifier: OutcomeClassifier = OutcomeClassifier()

    def run(self, state: StepState) -> Tuple[StepState, StepResult]:
        # 1. Validate input purity / contract
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

        # Run classifier
        result = self.classifier.classify(state, raw)

        # Canonical normalisation of cognitive output
        normalised = normalise_cognitive_structure(result.to_dict())

        # Enforce purity on the normalised structure
        enforce_cognitive_purity(normalised)

        return result

    def _apply_outcome(self, state: StepState, result: StepResult) -> StepState:
        # For now, keep it simple: DONE on success/continue/tool, ERROR on failure.
        if result.outcome == StepOutcome.FAILURE:
            new_status = StepStatus.ERROR
        else:
            new_status = StepStatus.DONE

        return state.replace(status=new_status)

    def _append_trace(self, state: StepState, result: StepResult) -> StepState:
        event = TRACE_BUILDER.classification(
            outcome=result.outcome.value,
            reason=result.reason,
            raw_classifier_output=state.cognitive_input.get("raw_classifier_output", {}),
            timestamp=state.created_at,
        )
        new_trace = state.trace + [event]
        return state.replace(trace=new_trace)


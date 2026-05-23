from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from src.core.planning.cognitive_normaliser import normalise_cognitive_structure

from .outcome_classifier import OutcomeClassifier
from src.core.types.step_state import StepState, StepStatus
from src.core.types.step_result import StepOutcome, StepResult
from src.core.types.hashing import stable_hash
from src.core.planning.cognitive_contract import validate_cognitive_input
from src.core.planning.trace_event import TraceEventBuilder
from src.core.planning.purity_enforcer import enforce_cognitive_purity
from src.core.planning.plan_generator import PlanGenerator, PlanPrompt

# In practice, you’d inject this or construct it at a higher level.
TRACE_BUILDER = TraceEventBuilder()

@dataclass(frozen=True)
class CoreStepV2:
    """
    Pure cognitive step executor (Stratum 2).
    """
    classifier: OutcomeClassifier = OutcomeClassifier()
    capabilities: dict = None
    plan_generator: PlanGenerator = PlanGenerator(capabilities=capabilities)

    def __post_init__(self):
        if self.capabilities is None:
            raise ValueError("CoreStepV2 requires a capabilities dictionary")
        if self.plan_generator is None:
            object.__setattr__(self, "plan_generator", PlanGenerator(capabilities=self.capabilities))

    def run(self, state: StepState) -> Tuple[StepState, StepResult]:
        # Validate input purity / contract
        validate_cognitive_input(
            state=state,
            last_result=state.last_result,
            memory_snapshot=state.cognitive_input.get("memory", {}),
        )

        # PLAN MODE
        if state.cognitive_input.get("mode") == "plan":
            return self._generate_plan(state)
        
        # Transition → RUNNING
        running_state = self._to_running(state)

        # Classify outcome (pure)
        result = self._classify(running_state)

        # Transition → DONE / ERROR based on outcome
        final_state = self._apply_outcome(running_state, result)

        # Append trace
        final_state = self._append_trace(final_state, result)

        # Return new_state, result
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

    def _generate_plan(self, state: StepState) -> Tuple[StepResult, StepState]:
        """
        Deterministic plan-generation path.
        Produces a PlanPrompt and wraps it in a StepResult.
        """
        plan_prompt: PlanPrompt = self.plan_generator.generate(state)

        result = StepResult(
            outcome=StepOutcome.SUCCESS,
            reason="plan_generated",
            cognitive_output={
                "kind": "plan_prompt",
                "prompt": plan_prompt.prompt,
                "metadata": plan_prompt.metadata,
            },
        )

        # Transition -> DONE
        final_state = state.replace(status=StepStatus.DONE)

        # Append trace
        event = TRACE_BUILDER.generic(
            kind="plan_prompt_generated",
            payload={
                "prompt": plan_prompt.prompt,
                "metadata": plan_prompt.metadata,
            },
            timestamp=state.created_at,
        )
        final_state = final_state.replace(trace=final_state.trace + [event])

        return result, final_state

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from src.core.planning.validators.cognitive_normaliser import normalise_cognitive_structure
from src.core.planning.validators.plan_validator import PlanValidator
from src.core.planning.models.plan import Plan

from .dispatch.outcome_classifier import OutcomeClassifier
from src.core.planning.models.step_state import StepState, StepStatus
from src.core.types.step_result import StepResult
from src.core.types.cognitive_step_outcome import CognitiveStepOutcome
from src.core.planning.models.cognitive_contract import validate_cognitive_input
from src.core.planning.events.trace_event import TraceEventBuilder
from src.core.planning.safety.purity_enforcer import enforce_cognitive_purity
from src.core.planning.generator.plan_generator import PlanGenerator, PlanPrompt

# In practice, you’d inject this or construct it at a higher level.
TRACE_BUILDER = TraceEventBuilder()

@dataclass(frozen=True)
class StepProcessor:
    """
    Pure cognitive step executor (Stratum 2).
    """
    classifier: OutcomeClassifier = OutcomeClassifier()
    capabilities: dict = None
    plan_generator: PlanGenerator = PlanGenerator(capabilities=capabilities)
    plan_validator: PlanValidator | None = None

    def __post_init__(self):
        if self.capabilities is None:
            raise ValueError("CoreStep requires a capabilities dictionary")
        if self.plan_generator is None:
            object.__setattr__(self, "plan_generator", PlanGenerator(capabilities=self.capabilities))

        if self.plan_validator is None:
            object.__setattr__(
                self,
                "plan_validator",
                PlanValidator(self.capabilities),
            )

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
        
        if state.cognitive_input.get("mode") == "plan_validate":
            return self._validate_plan(state)

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
        if "raw_classifier_output" not in state.cognitive_input:
            # No classifier output present; skip classification or return a safe default
            # You may want to return a default StepResult or handle as appropriate
            return StepResult.failure(
                reason="No classifier output present",
                payload={},
                trace=[],
            )
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
        if result.outcome == CognitiveStepOutcome.FAILURE:
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
            outcome=CognitiveStepOutcome.SUCCESS,
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

    def _validate_plan(self, state: StepState) -> tuple[StepState, StepResult]:
        raw_plan = state.cognitive_input.get("plan")
        if raw_plan is None:
            result = StepResult.failure(
                reason="No plan provided for validation",
                payload={"error_type": "PlanMissing"},
                trace=[],
            )
            return state, result

        try:
            plan = Plan.from_dict(raw_plan)
        except Exception as exc:
            result = StepResult.failure(
                reason="Invalid plan structure",
                payload={"error_type": "PlanDeserialisationError", "detail": str(exc)},
                trace=[],
            )
            return state, result

        target_skill_id = plan.targetskillid
        capability = self.capabilities.get(target_skill_id)
        if capability is None:
            result = StepResult.failure(
                reason=f"Unknown capability: {target_skill_id}",
                payload={"error_type": "UnknownCapability", "targetSkillId": target_skill_id},
                trace=[],
            )
            return state, result

        skill_schema = capability.get("input_schema", {})

        try:
            assert self.plan_validator is not None
            self.plan_validator.validate(plan, skill_schema)
        except Exception as exc:
            result = StepResult.failure(
                reason="Plan failed validation",
                payload={
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "targetSkillId": target_skill_id,
                },
                trace=[],
            )
            return state, result

        result = StepResult.success(
            reason="Plan validated successfully",
            payload={
                "targetSkillId": target_skill_id,
                "intent": plan.intent,
            },
            trace=[],
        )
        return state, result

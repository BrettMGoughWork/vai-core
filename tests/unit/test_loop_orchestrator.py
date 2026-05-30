from src.core.planning.orchestration.loop_orchestrator import LoopOrchestrator
from src.core.planning.safety.loop_policy import LoopPolicy
from src.core.planning.models.step_state import StepState, StepStatus
from src.core.types.step_result import StepResult
from src.core.types.cognitive_step_outcome import CognitiveStepOutcome as StepOutcome
from src.core.planning.step_processor import StepProcessor

from src.core.planning.generator.plan_generator import PlanGenerator


# Minimal fake capabilities manifest (required by CoreStepV2 + PlanGenerator)
FAKE_CAPABILITIES = {
    "echo": {
        "name": "echo",
        "version": "1.0",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    }
}


# --- Fake CoreStepV2 for deterministic testing ---
class FakeCoreStep:
    def __init__(self):
        self.counter = 0

    def run(self, state):
        self.counter += 1

        if self.counter < 3:
            outcome = StepOutcome.CONTINUE
        else:
            outcome = StepOutcome.SUCCESS

        result = StepResult(
            outcome=outcome,
            reason="test",
            payload={},
            trace=[],
        )

        new_state = state.replace(
            status=StepStatus.RUNNING,
            last_result={"outcome": outcome.value},
            created_at=state.created_at + 1,
        )

        return new_state, result


# --- Fake policy that always allows continue ---
class AlwaysAllowPolicy(LoopPolicy):
    def allows_continue(self, state, result, step_count):
        return True


def test_loop_orchestrator_basic():
    initial = StepState(
        step_id="test",
        parent_id=None,
        cognitive_input={},
        last_result=None,
        status=StepStatus.PENDING,
        created_at=0,
        attempt=0,
        trace=[],
        canonical_hash="x",
    )

    # Wrap FakeCoreStep inside a StepProcessor so the orchestrator can use it
    from src.core.planning.validators.plan_validator import PlanValidator
    core_step = StepProcessor(
        classifier=FakeCoreStep(),          # <-- this is the fake step logic
        capabilities=FAKE_CAPABILITIES,     # <-- required by StepProcessor
        plan_generator=PlanGenerator(FAKE_CAPABILITIES),
        plan_validator=PlanValidator(FAKE_CAPABILITIES),
    )

    orchestrator = LoopOrchestrator(
        core_step=FakeCoreStep(),
        max_steps=10,
        max_duration=100,
        policy=AlwaysAllowPolicy(),
    )

    final_state, final_result, metrics = orchestrator.run(initial)

    # Assertions
    assert final_result.outcome == StepOutcome.SUCCESS
    assert metrics.step_count == 3
    assert metrics.duration == 3
    assert metrics.termination_reason == "success"
    
    print("OK: Loop orchestrator basic test passed.")
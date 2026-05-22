from src.core.planning.loop_orchestrator import LoopOrchestrator
from src.core.planning.loop_controller import LoopPolicy
from src.core.planning.step_state import StepState, StepStatus
from src.core.planning.step_result import StepOutcome, StepResult
from src.core.planning.core_step_v2 import CoreStepV2


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

def test_loop_step_budget_exceeded():
    class FakeCoreStep:
        def run(self, state):
            # Always continue
            result = StepResult(
                outcome=StepOutcome.CONTINUE,
                reason="keep going",
                payload={},
                trace=[],
            )
            new_state = state.replace(
                status=StepStatus.RUNNING,
                last_result={"outcome": "continue"},
                created_at=state.created_at + 1,
            )
            return new_state, result

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

    orchestrator = LoopOrchestrator(
        core_step=FakeCoreStep(),
        max_steps=2,
        max_duration=100,
        policy=AlwaysAllowPolicy(),
    )

    final_state, final_result, metrics = orchestrator.run(initial)

    assert final_result.outcome == StepOutcome.CONTINUE
    assert metrics.step_count == 2
    assert metrics.termination_reason == "step_budget_exceeded"

def test_loop_duration_budget_exceeded():
    class FakeCoreStep:
        def run(self, state):
            result = StepResult(
                outcome=StepOutcome.CONTINUE,
                reason="keep going",
                payload={},
                trace=[],
            )
            new_state = state.replace(
                status=StepStatus.RUNNING,
                last_result={"outcome": "continue"},
                created_at=state.created_at + 50, # big jumps
            )
            return new_state, result

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

    orchestrator = LoopOrchestrator(
        core_step=FakeCoreStep(),
        max_steps=10,
        max_duration=60, # will exceed on 2nd iteration
        policy=AlwaysAllowPolicy(),
    )

    final_state, final_result, metrics = orchestrator.run(initial)

    assert final_result.outcome == StepOutcome.CONTINUE
    assert metrics.step_count == 2
    assert metrics.termination_reason == "duration_budget_exceeded"

def test_loop_policy_violation():
    class FakeCoreStep:
        def run(self, state):
            result = StepResult(
                outcome=StepOutcome.CONTINUE,
                reason="keep going",
                payload={},
                trace=[],
            )
            new_state = state.replace(
                status=StepStatus.RUNNING,
                last_result={"outcome": "continue"},
                created_at=state.created_at + 1,
            )
            return new_state, result

    class DenyPolicy(LoopPolicy):
        def allows_continue(self, state, result, step_count):
            return False # immediate violation

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

    orchestrator = LoopOrchestrator(
        core_step=FakeCoreStep(),
        max_steps=10,
        max_duration=100,
        policy=DenyPolicy(),
    )

    final_state, final_result, metrics = orchestrator.run(initial)

    assert final_result.outcome == StepOutcome.CONTINUE
    assert metrics.step_count == 1
    assert metrics.termination_reason == "policy_violation"

def test_loop_failure_termination():
    class FakeCoreStep:
        def run(self, state):
            result = StepResult(
                outcome=StepOutcome.FAILURE,
                reason="boom",
                payload={},
                trace=[],
            )
            new_state = state.replace(
                status=StepStatus.RUNNING,
                last_result={"outcome": "failure"},
                created_at=state.created_at + 1,
            )
            return new_state, result

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

    orchestrator = LoopOrchestrator(
        core_step=FakeCoreStep(),
        max_steps=10,
        max_duration=100,
        policy=AlwaysAllowPolicy(),
    )

    final_state, final_result, metrics = orchestrator.run(initial)

    assert final_result.outcome == StepOutcome.FAILURE
    assert metrics.step_count == 1
    assert metrics.termination_reason == "failure"

def test_loop_tool_needed_termination():
    class FakeCoreStep:
        def run(self, state):
            result = StepResult(
                outcome=StepOutcome.TOOL_NEEDED,
                reason="need tool",
                payload={"tool": "fake"},
                trace=[],
            )
            new_state = state.replace(
                status=StepStatus.RUNNING,
                last_result={"outcome": "tool_needed"},
                created_at=state.created_at + 1,
            )
            return new_state, result

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

    orchestrator = LoopOrchestrator(
        core_step=FakeCoreStep(),
        max_steps=10,
        max_duration=100,
        policy=AlwaysAllowPolicy(),
    )

    final_state, final_result, metrics = orchestrator.run(initial)

    assert final_result.outcome == StepOutcome.TOOL_NEEDED
    assert metrics.step_count == 1
    assert metrics.termination_reason == "tool_needed"
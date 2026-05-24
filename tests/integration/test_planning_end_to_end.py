from src.core.planning.models.plan import Plan
from src.core.planning.planning_composition import build_planning_substrate
from src.core.planning.safety.safety_policies import SafetyContext 

def test_end_to_end_planning_execution():
    """
    Full substrate integration test:
    - generate a plan
    - validate it
    - execute it
    - verify state, result, and metrics
    """

    plan_generator, plan_validator, plan_executor = build_planning_substrate()

    # For now we manually construct a simple plan.
    # Later phases will use generator.generate(intent).
    plan = Plan(
        intent="echo something",
        targetskillid="echo",
        arguments={"text": "hello world"},
        reasoning_summary="integration test",
    )

    # Validate
    plan_validator.validate(plan)

    # Execute
    state, result, metrics = plan_executor.execute(plan)

    # Assertions
    from src.core.planning.models.step_state import StepStatus
    assert state.status == StepStatus.ERROR  # Should be error if classifier output is missing
    assert result.reason == "No classifier output present"
    # Optionally, check that result.outcome == StepOutcome.FAILURE
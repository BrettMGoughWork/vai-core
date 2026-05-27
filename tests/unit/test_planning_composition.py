from src.core.planning import build_planning_substrate


def test_planning_substrate_composes():
    plan_generator, plan_validator, plan_executor = build_planning_substrate()

    assert plan_generator is not None
    assert plan_validator is not None
    assert plan_executor is not None



from src.core.state.config import AgentConfig, LoopPolicy
from src.primitives.runtime.categories import SkillCategory
from src.primitives.runtime.side_effects import SideEffect


def test_loop_policy_defaults():
    policy = LoopPolicy()
    assert policy.max_steps == 5
    assert policy.max_wall_time is None
    assert policy.max_errors == 1
    assert policy.max_fatals == 1
    assert policy.per_step_timeout is None


def test_loop_policy_custom_values():
    policy = LoopPolicy(max_steps=10, max_wall_time=60.0, max_errors=3, max_fatals=2, per_step_timeout=5.0)
    assert policy.max_steps == 10
    assert policy.max_wall_time == 60.0
    assert policy.max_errors == 3
    assert policy.max_fatals == 2
    assert policy.per_step_timeout == 5.0


def test_agent_config_has_default_loop_policy():
    config = AgentConfig(
        model="test-model",
        allowed_tools=["echo"],
        allowed_categories=[SkillCategory.GENERAL],
        allowed_side_effects=[SideEffect.NONE],
    )
    assert isinstance(config.loop_policy, LoopPolicy)
    assert config.loop_policy.max_steps == 5


def test_agent_config_from_yaml_without_loop_policy():
    data = {
        "model": "test-model",
        "allowed_tools": ["echo"],
        "allowed_categories": [SkillCategory.GENERAL],
        "allowed_side_effects": [SideEffect.NONE],
    }
    config = AgentConfig.from_yaml(data)
    assert config.model == "test-model"
    assert config.loop_policy.max_steps == 5


def test_agent_config_from_yaml_with_loop_policy():
    data = {
        "model": "test-model",
        "allowed_tools": ["echo"],
        "allowed_categories": [SkillCategory.GENERAL],
        "allowed_side_effects": [SideEffect.NONE],
        "loop_policy": {"max_steps": 8, "max_wall_time": 30.0, "max_errors": 2, "per_step_timeout": 10.0},
    }
    config = AgentConfig.from_yaml(data)
    assert config.model == "test-model"
    assert config.loop_policy.max_steps == 8
    assert config.loop_policy.max_wall_time == 30.0
    assert config.loop_policy.max_errors == 2
    assert config.loop_policy.per_step_timeout == 10.0
    assert config.loop_policy.max_fatals == 1  # default value

from src.core.state.isdone import isdone
from src.core.state.step_outcome import StepOutcome
from src.core.state.state import ConversationState
from src.core.state.config import AgentConfig, LoopPolicyConfig


def test_isdone_true_on_success():
    state = ConversationState(input="test")
    state.metadata["step_count"] = 0
    config = AgentConfig(
        model="gpt-4",
        allowed_tools=[],
        allowed_categories=[],
        allowed_side_effects=[],
        max_steps=4
    )
    assert isdone(state, StepOutcome.SUCCESS, config) is True


def test_isdone_true_on_fatal():
    state = ConversationState(input="test")
    state.metadata["step_count"] = 0
    config = AgentConfig(
        model="gpt-4",
        allowed_tools=[],
        allowed_categories=[],
        allowed_side_effects=[],
        max_steps=4
    )
    assert isdone(state, StepOutcome.FATAL, config) is True


def test_isdone_true_on_max_steps():
    state = ConversationState(input="test")
    state.metadata["step_count"] = 4
    config = AgentConfig(
        model="gpt-4",
        allowed_tools=[],
        allowed_categories=[],
        allowed_side_effects=[],
        max_steps=4,
        loop_policy=LoopPolicyConfig(max_steps=4)
    )
    assert isdone(state, StepOutcome.RECOVERABLE, config) is True


def test_isdone_false_on_recoverable():
    state = ConversationState(input="test")
    state.metadata["step_count"] = 2
    config = AgentConfig(
        model="gpt-4",
        allowed_tools=[],
        allowed_categories=[],
        allowed_side_effects=[],
        max_steps=4
    )
    assert isdone(state, StepOutcome.RECOVERABLE, config) is False


def test_isdone_false_on_noop():
    state = ConversationState(input="test")
    state.metadata["step_count"] = 1
    config = AgentConfig(
        model="gpt-4",
        allowed_tools=[],
        allowed_categories=[],
        allowed_side_effects=[],
        max_steps=4
    )
    assert isdone(state, StepOutcome.NOOP, config) is False

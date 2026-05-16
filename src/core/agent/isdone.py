from src.core.agent.outcome import StepOutcome
from src.core.agent.state import ConversationState
from src.core.agent.config import AgentConfig


def isdone(state: ConversationState, outcome: StepOutcome, config: AgentConfig) -> bool:
    """
    Determine if the agent should stop running.

    Returns True if:
    - outcome is SUCCESS or FATAL
    - max_steps reached
    """
    if outcome in (StepOutcome.SUCCESS, StepOutcome.FATAL):
        return True
    attr_count = getattr(state, "step_count", 0)
    meta_count = state.metadata.get("step_count", attr_count)
    if not isinstance(attr_count, int):
        attr_count = 0
    if not isinstance(meta_count, int):
        meta_count = 0
    step_count = max(attr_count, meta_count)
    if step_count >= config.max_steps:
        return True
    return False

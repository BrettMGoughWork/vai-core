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
    step_count = getattr(state, 'step_count', state.metadata.get('step_count', 0))
    if step_count >= config.max_steps:
        return True
    return False

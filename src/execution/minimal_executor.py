from src.core.state.state import ConversationState
from src.core.state.outcome import StepOutcome
from src.core.types.result import CoreResult
from src.execution.safe_failure import SafeFailure
from src.core.config.model import AgentConfig


class MinimalCoreStepExecutor:
    def __init__(self, llm):
        self.llm = llm

    def execute(
        self,
        step: object,
        state: ConversationState,
        config: AgentConfig,
    ):
        """
        Runtime expects:
            (result, new_state, outcome)
        """

        # super minimal: treat step as "just run the llm on state.input"
        try:
            text = self.llm.complete(state.input)
            result = CoreResult.from_text(text)
            new_state = state
            outcome = StepOutcome.SUCCESS
            return result, new_state, outcome
        except Exception as e:
            failure = SafeFailure.from_exception(e)
            new_state = state
            outcome = StepOutcome.FATAL
            return failure, new_state, outcome
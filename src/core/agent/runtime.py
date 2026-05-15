from typing import Optional

from src.core.agent.state import ConversationState
from src.core.agent.corestep import core_step
from src.core.agent.outcome import StepOutcome
from src.core.agent.config import AgentConfig
from src.core.llm.transport import LLMTransport
from src.core.types.result import CoreResult

class AgentRuntime:
    def __init__(self, transport: LLMTransport, config: AgentConfig):
        self.transport = transport
        self.config = config

    def step(self, prompt: str) -> CoreResult:
        state = ConversationState(input=prompt)
        result, _, _ = core_step(state, self.transport, self.config)
        return result

    def run(self, prompt: str) -> CoreResult:
        state = ConversationState(input=prompt)
        last: Optional[CoreResult] = None

        for _ in range(self.config.max_steps):
            result, state, outcome = core_step(state, self.transport, self.config)
            last = result

            if outcome in (StepOutcome.SUCCESS, StepOutcome.FATAL):
                return result

            # RECOVERABLE -> continue
            # NOOP -> continue (Step 16 will refine this)

        return last or CoreResult.from_error(
            RuntimeError("Agent reached max_steps without result")
        )

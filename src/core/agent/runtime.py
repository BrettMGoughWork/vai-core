from typing import Optional

from src.core.agent.state import ConversationState
from src.core.agent.corestep import core_step
from src.core.agent.outcome import StepOutcome
from src.core.agent.config import AgentConfig
from src.core.agent.isdone import isdone
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
        outcome = StepOutcome.NOOP
        result = None

        while not isdone(state, outcome, self.config):
            result, state, outcome = core_step(state, self.transport, self.config)

        return result or CoreResult.from_error(
            RuntimeError("Agent reached max_steps without result")
        )

from typing import Optional
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError

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
        timeout = self.config.loop_policy.per_step_timeout
        max_wall_time = self.config.loop_policy.max_wall_time
        loop_start = time.monotonic()

        while not isdone(state, outcome, self.config):
            if max_wall_time is not None:
                elapsed = time.monotonic() - loop_start
                if elapsed > max_wall_time:
                    outcome = StepOutcome.FATAL
                    state.last_error = "Loop exceeded max wall time"
                    break

            if timeout is not None:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(core_step, state, self.transport, self.config)
                    try:
                        result, state, outcome = future.result(timeout=timeout)
                    except TimeoutError:
                        outcome = StepOutcome.FATAL
                        state.last_error = "Step timed out"
                        break
            else:
                result, state, outcome = core_step(state, self.transport, self.config)

        return result or CoreResult.from_error(
            RuntimeError("Agent reached max_steps without result")
        )
